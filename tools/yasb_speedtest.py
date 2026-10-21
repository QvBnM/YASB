"""
yasb_speedtest.py - on-demand internet speed test for the YASB bar.

    py  -3.14 yasb_speedtest.py --status   # print the last result as JSON (read by the bar every few seconds)
    pyw -3.14 yasb_speedtest.py --run      # run a test now (click on the bar item)

Measures against Cloudflare's speed test endpoints (speed.cloudflare.com, the same ones
the website uses) with only the standard library; falls back to `speedtest-cli` if
Cloudflare can't be reached. The test only runs when you click, never on its own,
so it does not eat your bandwidth.

    py -3.14 yasb_speedtest.py --run --verbose   # run in the console and print the result / error
Results are kept in %LOCALAPPDATA%\\yasb-palette\\speedtest.json.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import statistics
import sys
import threading
import time
from pathlib import Path

CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "yasb-palette"
RESULT = CACHE_DIR / "speedtest.json"
STALE_RUNNING_SECONDS = 120  # a "running" state older than this means the test died


def _read() -> dict:
    try:
        return json.loads(RESULT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(data, f)


def status() -> dict:
    d = _read()
    state = d.get("state", "idle")
    if state == "running" and time.time() - d.get("started", 0) > STALE_RUNNING_SECONDS:
        state = "error"
        d["error"] = "testul nu s-a terminat"
    if state == "running":
        return {
            "label": "testez…",
            "alt": "testez… (15-30 s)",
            "tooltip": "Testul ruleaza (15-30 s)",
            "state": "running",
        }
    if state == "ok":
        when = time.strftime("%H:%M", time.localtime(d.get("finished", time.time())))
        return {
            "label": f"↓{d['down']:.0f} ↑{d['up']:.0f}",
            "alt": f"ping {d['ping']:.0f} ms · {when}",
            "tooltip": f"Download {d['down']:.1f} Mbps\nUpload {d['up']:.1f} Mbps\nPing {d['ping']:.0f} ms\n"
            f"Server: {d.get('server', '?')}\nTestat la {when}. Click pentru un test nou.",
            "state": "ok",
        }
    if state == "error":
        return {
            "label": "eroare",
            "alt": "click = reincearca",
            "tooltip": f"Testul a eșuat: {d.get('error', '?')}\nClick pentru a reîncerca.",
            "state": "error",
        }
    return {
        "label": "test",
        "alt": "click = test",
        "tooltip": "Click pentru un test de viteză (Mbps)",
        "state": "idle",
    }


def _single_instance():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(CACHE_DIR / "speedtest.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        return None


CF_HOST = os.environ.get("YASB_SPEEDTEST_HOST", "speed.cloudflare.com")
CF_SECURE = os.environ.get("YASB_SPEEDTEST_PLAIN") != "1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) yasb-speedtest",
    "Accept": "*/*",
    # without a Referer, Cloudflare answers large __down requests with 429 (empty body)
    "Referer": "https://speed.cloudflare.com/",
    "Origin": "https://speed.cloudflare.com",
}
STREAMS = 4
DOWN_SECONDS = 8.0
UP_SECONDS = 6.0
DOWN_CHUNK = 25_000_000
UP_CHUNK = 4_000_000


class HttpError(RuntimeError):
    def __init__(self, status: int, retry_after: str | None = None):
        self.status = status
        self.retry_after = retry_after
        if status == 429:
            mins = ""
            if retry_after and retry_after.isdigit():
                mins = (
                    f" (mai incearca peste ~{max(1, round(int(retry_after) / 60))} min)"
                )
            msg = f"Cloudflare limiteaza testele: prea multe intr-o ora{mins}"
        else:
            msg = f"Cloudflare a refuzat cererea (HTTP {status})"
        super().__init__(msg)


def _conn(timeout: float = 15.0) -> http.client.HTTPConnection:
    if CF_SECURE:
        return http.client.HTTPSConnection(
            CF_HOST, timeout=timeout, context=ssl.create_default_context()
        )
    return http.client.HTTPConnection(CF_HOST, timeout=timeout)


def _request(
    conn, method: str, path: str, body: bytes | None = None, sink=None
) -> dict:
    headers = dict(HEADERS)
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    if resp.status >= 400:
        resp.read()  # drain; nothing of an error page counts as measured data
        raise HttpError(resp.status, resp.getheader("Retry-After"))
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        if sink is not None and not sink(len(chunk)):
            conn.close()  # time is up: drop the rest of this response
            break
    return {k.lower(): v for k, v in resp.getheaders()}


def _ping(samples: int = 6) -> tuple[float, str]:
    conn = _conn()
    try:
        colo = _request(conn, "GET", "/__down?bytes=0").get("cf-meta-colo", "")
        times = []
        for _ in range(samples):
            t0 = time.perf_counter()
            _request(conn, "GET", "/__down?bytes=0")
            times.append((time.perf_counter() - t0) * 1000)
        return statistics.median(times), colo
    finally:
        conn.close()


def _parallel(worker, seconds: float) -> float:
    lock = threading.Lock()
    state = {"bytes": 0, "errors": []}
    deadline = time.perf_counter() + seconds

    def add(n: int) -> bool:
        with lock:
            state["bytes"] += n
        return time.perf_counter() < deadline

    def run_one():
        try:
            while time.perf_counter() < deadline:
                worker(add)
        except Exception as e:
            state["errors"].append(e)

    start = time.perf_counter()
    threads = [threading.Thread(target=run_one, daemon=True) for _ in range(STREAMS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(seconds + 20)
    elapsed = max(min(time.perf_counter(), deadline + 1) - start, 0.5)
    if state["errors"] and state["bytes"] < 200_000:
        raise state["errors"][0]  # a refusal, not a slow line
    if state["bytes"] == 0:
        raise RuntimeError("nu s-au transferat date")
    return state["bytes"] * 8 / elapsed / 1_000_000


_down_chunk = [DOWN_CHUNK]


def _download_worker(add) -> None:
    conn = _conn()
    try:
        while True:
            try:
                _request(conn, "GET", f"/__down?bytes={_down_chunk[0]}", sink=add)
            except HttpError as e:
                if e.status == 403 and _down_chunk[0] > 2_000_000:
                    _down_chunk[0] //= 2  # refused for size: ask for smaller pieces
                    conn.close()
                    conn = _conn()
                    continue
                raise
            if not add(0):
                return
    finally:
        conn.close()


def _upload_worker(add) -> None:
    body = _upload_body()
    conn = _conn(timeout=30)
    try:
        while True:
            t0 = time.perf_counter()
            _request(conn, "POST", "/__up", body=body)
            if not add(len(body)) or time.perf_counter() - t0 > UP_SECONDS:
                return
    finally:
        conn.close()


_body_cache: list[bytes] = []


def _upload_body() -> bytes:
    if not _body_cache:
        _body_cache.append(os.urandom(UP_CHUNK))
    return _body_cache[0]


def run_speedtest() -> dict:
    ping, colo = _ping()
    down = _parallel(_download_worker, DOWN_SECONDS)
    up = _parallel(_upload_worker, UP_SECONDS)
    return {
        "down": down,
        "up": up,
        "ping": ping,
        "server": f"Cloudflare {colo}".strip(),
    }


cloudflare_test = run_speedtest


def speedtest_net_test() -> dict:
    import speedtest  # pip install speedtest-cli

    st = speedtest.Speedtest(secure=True)
    best = st.get_best_server()
    st.download()
    st.upload(pre_allocate=False)
    r = st.results
    return {
        "down": r.download / 1_000_000,
        "up": r.upload / 1_000_000,
        "ping": r.ping,
        "server": f"speedtest.net: {best.get('sponsor', '?')} ({best.get('name', '?')})",
    }


def _describe(e: Exception) -> str:
    text = str(e) or type(e).__name__
    if isinstance(e, ssl.SSLError):
        return f"certificat/SSL: {text}"
    if isinstance(e, OSError) and not isinstance(e, ConnectionError):
        return f"retea: {text}"
    return text


def run(verbose: bool = False) -> int:
    lock = _single_instance()
    if lock is None:
        if verbose:
            print("Un test ruleaza deja.")
        return 0  # a test is already running: ignore the extra click
    previous = _read()
    _write({**previous, "state": "running", "started": time.time()})
    errors = []
    result = None
    for name, test in (
        ("Cloudflare", cloudflare_test),
        ("speedtest.net", speedtest_net_test),
    ):
        try:
            if verbose:
                print(f"Testez cu {name}...")
            result = test()
            break
        except Exception as e:
            errors.append(f"{name}: {_describe(e)}")
            if verbose:
                print(f"  esuat: {_describe(e)}")
    if result is not None:
        _write({"state": "ok", **result, "finished": time.time()})
        if verbose:
            print(
                f"Download {result['down']:.1f} Mbps, upload {result['up']:.1f} Mbps, ping {result['ping']:.0f} ms ({result['server']})"
            )
        return 0
    _write({"state": "error", "error": " | ".join(errors), "finished": time.time()})
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--run", action="store_true", help="run a speed test now")
    ap.add_argument(
        "--status", action="store_true", help="print the last result as JSON"
    )
    ap.add_argument(
        "--verbose", action="store_true", help="with --run: print progress and errors"
    )
    args = ap.parse_args()
    if args.run:
        return run(args.verbose)
    # ASCII-only JSON (ă, ↓ become \uXXXX): when YASB reads this through a pipe, Windows
    # uses the ANSI code page (cp1252), which cannot encode "ă" and crashed the script,
    # so the bar showed the raw "{data[label]}".
    sys.stdout.write(json.dumps(status(), ensure_ascii=True))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
