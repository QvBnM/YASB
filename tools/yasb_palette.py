"""
yasb_palette.py - recolors YASB from the current Windows wallpaper.

    pyw -3.14 yasb_palette.py            # watch: recolor every time the wallpaper changes
    py  -3.14 yasb_palette.py --once     # recolor once from the current wallpaper and exit
    py  -3.14 yasb_palette.py --image C:\\path\\pic.jpg --once
    py  -3.14 yasb_palette.py --diagnose # what wallpaper / Wallpaper Engine profile is detected

Wallpaper source: Wallpaper Engine when it is running (the preview image of the
active wallpaper on the first monitor), otherwise the Windows desktop wallpaper.

Colors come from pywal (pywal16) when it is installed, otherwise from a built-in
Pillow extractor. Either way the palette is then *made readable*: every text
color is checked against its background with the WCAG contrast formula and its
lightness is nudged (hue kept) until it passes:

    text on bar        >= 7.0     secondary text >= 4.5     accent on bar >= 4.5
    text on accent     >= 4.5     muted/decor    >= 2.2

Writes (atomically) to %USERPROFILE%\\.config\\yasb (or %YASB_CONFIG_HOME%):
    palette.css   :root { --bar: ...; } variables used by styles.css (YASB reloads it by itself)
    palette.json  the same palette, read live by the Audio Orbit panel
"""

from __future__ import annotations

import argparse
import colorsys
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("YASB_CONFIG_HOME") or Path.home() / ".config" / "yasb")
CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "yasb-palette"
TRANSCODED = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
POLL_SECONDS = 2.0

# Used when nothing can be extracted (and as the palette shipped with the theme)
FALLBACK = {"bg": "#101716", "candidates": ["#7dd9c7", "#b9d4f0", "#e6b980"]}

log = logging.getLogger("yasb_palette")


# --------------------------------------------------------------------------- color math
def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")[:6]
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def hls(h: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*hex_to_rgb(h))


def from_hls(h: float, light: float, sat: float) -> str:
    return rgb_to_hex(colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, light)), max(0.0, min(1.0, sat))))


def luminance(h: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in hex_to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ensure_contrast(color: str, against: str, minimum: float, direction: str = "auto") -> str:
    """Move `color`'s lightness (keeping hue and saturation) until it reaches `minimum`
    contrast against `against`. Light colors go lighter on dark backgrounds."""
    if contrast(color, against) >= minimum:
        return color
    h, light, s = hls(color)
    if direction == "auto":
        direction = "up" if luminance(against) < 0.18 else "down"
    step = 0.01 if direction == "up" else -0.01
    while 0.0 <= light <= 1.0:
        light += step
        candidate = from_hls(h, light, s)
        if contrast(candidate, against) >= minimum:
            return candidate
    return "#ffffff" if direction == "up" else "#000000"


def hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d) * 360


# --------------------------------------------------------------------------- extraction
def extract_with_pywal(image: Path) -> dict | None:
    try:
        import pywal  # pywal16
    except Exception:
        return None
    for backend in ("colorthief", "haishoku", "colorz", "wal"):
        try:
            result = pywal.colors.get(str(image), backend=backend, cache_dir=str(CACHE_DIR / "wal"))
            colors = result["colors"]
            candidates = [colors[f"color{i}"] for i in (1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14)]
            log.info("pywal backend %s", backend)
            return {"bg": result["special"]["background"], "candidates": candidates, "source": f"pywal/{backend}"}
        except Exception as e:  # backend missing or failed: try the next one
            log.debug("pywal backend %s failed: %s", backend, e)
    return None


def extract_with_pillow(image: Path) -> dict | None:
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        with Image.open(image) as im:
            im = im.convert("RGB")
            im.thumbnail((240, 240))
            q = im.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
            pal = q.getpalette() or []
            counts = sorted(q.getcolors() or [], reverse=True)
    except Exception as e:
        log.warning("Pillow could not read %s: %s", image, e)
        return None
    swatches = []
    for count, idx in counts:
        r, g, b = pal[idx * 3 : idx * 3 + 3]
        swatches.append((count, rgb_to_hex((r / 255, g / 255, b / 255))))
    if not swatches:
        return None
    # background hue: the dominant color; accents: everything, ranked later by colorfulness
    return {"bg": swatches[0][1], "candidates": [c for _, c in swatches], "source": "pillow"}


# --------------------------------------------------------------------------- palette
def build_palette(bg: str, candidates: list[str]) -> dict[str, str]:
    # accent = the most colorful candidate (not gray, not near-black, not near-white)
    def score(c: str) -> float:
        _h, light, s = hls(c)
        if s < 0.16 or light < 0.15 or light > 0.9:
            return -1
        return s * (1 - abs(light - 0.58) * 1.4)

    ranked = sorted(set(candidates), key=score, reverse=True)
    has_accent = bool(ranked) and score(ranked[0]) > 0
    acc = ranked[0] if has_accent else "#7dd9c7"
    ah, al, as_ = hls(acc)
    accent = from_hls(ah, min(max(al, 0.62), 0.78), min(max(as_, 0.45), 0.75))
    second = next((c for c in ranked[1:] if score(c) > 0 and hue_distance(hls(c)[0], ah) >= 40), None)
    sh, _sl, ss = hls(second) if second else ((ah + 0.12) % 1.0, 0, 0.5)
    accent2 = from_hls(sh, 0.80, min(max(ss, 0.35), 0.6))

    # dark surfaces take the wallpaper's hue: pywal's background when it has a real hue,
    # otherwise the accent's hue (pywal often returns an almost gray background).
    # A gray wallpaper (no accent found) stays neutral.
    bh, bl, bs = hls(bg)
    if bs >= 0.15 and 0.06 <= bl <= 0.94 and has_accent:
        hue, tint = bh, min(bs, 0.32)
    elif has_accent:
        hue, tint = ah, 0.24
    else:
        hue, tint = bh, 0.03

    def surface(light: float, sat_k: float = 1.0) -> str:
        return from_hls(hue, light, tint * sat_k)

    p = {
        "bar": surface(0.075),
        "panel": surface(0.090),
        "card": surface(0.115),
        "hover": surface(0.155),
        "line": surface(0.215, 0.8),
        "track": surface(0.185, 0.8),
        "dot": surface(0.300, 0.7),
        "dot2": surface(0.235, 0.7),
    }
    p["text"] = from_hls(hue, 0.92, min(tint, 0.14))
    p["text2"] = from_hls(hue, 0.82, min(tint, 0.12))
    p["sub"] = from_hls(hue, 0.62, min(tint, 0.14))
    p["muted"] = from_hls(hue, 0.40, min(tint, 0.14))

    # ---- readability: enforce WCAG contrast
    p["text"] = ensure_contrast(p["text"], p["bar"], 7.0)
    p["text"] = ensure_contrast(p["text"], p["card"], 7.0)
    p["text2"] = ensure_contrast(p["text2"], p["bar"], 6.0)
    p["sub"] = ensure_contrast(p["sub"], p["bar"], 4.5)
    p["sub"] = ensure_contrast(p["sub"], p["card"], 4.5)
    p["muted"] = ensure_contrast(p["muted"], p["bar"], 2.2)
    p["on"] = p["bar"]  # dark text on colored pills
    accent = ensure_contrast(accent, p["bar"], 4.5, "up")  # accent used as text (clock)
    accent = ensure_contrast(accent, p["on"], 4.5, "up")  # dark text on accent pills
    accent2 = ensure_contrast(accent2, p["on"], 4.5, "up")
    p["accent"], p["accent2"] = accent, accent2
    p["danger"] = ensure_contrast("#e78a8a", p["on"], 4.5, "up")
    # warn = values over a threshold (yellow). If the accent is itself yellow, lean orange so the
    # two never look alike. Used as text on the bar, so the same 4.5:1 rule as the accent.
    ah = hls(accent)[0]
    warn_hue = 0.085 if abs(ah - 0.125) < 0.05 else 0.125
    p["warn"] = ensure_contrast(from_hls(warn_hue, 0.69, 0.62), p["bar"], 4.5, "up")
    p["white"] = ensure_contrast(from_hls(hue, 0.95, min(tint, 0.08)), p["on"], 7.0, "up")
    return p


def orbit_colors(p: dict[str, str]) -> dict[str, str]:
    """Map to the keys the Audio Orbit canvas understands."""
    return {
        "background": p["panel"],
        "border": p["line"],
        "accent": p["accent"],
        "on_accent": p["on"],
        "card": p["card"],
        "card_hover": p["hover"],
        "text": p["text"],
        "subtext": p["sub"],
        "muted": p["muted"],
        "danger": p["danger"],
    }


def write_outputs(p: dict[str, str], source: str, image: Path | None) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    css = ["/* generated by yasb_palette.py - " + source + " - do not edit */", ":root {"]
    css += [f"    --{k}: {v};" for k, v in p.items()]
    # "r, g, b" variants for translucent backgrounds: rgba(var(--panel-rgb), 0.92)
    css += [f"    --{k}-rgb: {', '.join(str(round(c * 255)) for c in hex_to_rgb(v))};" for k, v in p.items()]
    css.append("}")
    payload = {"source": source, "image": str(image) if image else None, "palette": p, "orbit": orbit_colors(p)}
    # Written IN PLACE on purpose: YASB's stylesheet watcher reacts to "modified" events
    # only, and a temp-file + rename shows up as a move, so the bar would never reload.
    # The files are tiny and written in a single call, so a reader never sees half a file.
    for name, text in (("palette.json", json.dumps(payload, indent=2)), ("palette.css", "\n".join(css) + "\n")):
        _write_in_place(CONFIG_DIR / name, text)
    for leftover in CONFIG_DIR.glob("palette.*.tmp"):  # from older versions of this script
        try:
            leftover.unlink()
        except OSError:
            pass
    log.info("palette written (%s): accent %s, bar %s", source, p["accent"], p["bar"])


def _write_in_place(path: Path, text: str, attempts: int = 20) -> None:
    """Overwrite `path` in place; retry while another process briefly holds it."""
    data = text.encode("utf-8")
    for i in range(attempts):
        try:
            with open(path, "r+b" if path.exists() else "wb") as f:
                f.write(data)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            return
        except PermissionError:
            time.sleep(0.1 * (i + 1))
    raise PermissionError(f"could not write {path} (file kept busy by another program)")


# --------------------------------------------------------------------------- wallpaper
def current_wallpaper() -> Path | None:
    if TRANSCODED.is_file():
        return TRANSCODED  # always the image Windows actually shows (slideshow / Spotlight too)
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as k:
            path = Path(winreg.QueryValueEx(k, "WallPaper")[0])
        return path if path.is_file() else None
    except Exception:
        return None


def fingerprint(path: Path) -> tuple[float, int] | None:
    try:
        st = path.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


# --------------------------------------------------------------------------- Wallpaper Engine
WE_PROCESSES = ("wallpaper64.exe", "wallpaper32.exe")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tga"}
_we_cache: tuple[float, list[tuple[str, int]]] = (0.0, [])


def wallpaper_engine_processes() -> list[tuple[str, int]]:
    """[(exe name, pid)] of running Wallpaper Engine processes; checked at most every 10 s."""
    global _we_cache
    now = time.monotonic()
    if now - _we_cache[0] < 10:
        return _we_cache[1]
    found: list[tuple[str, int]] = []
    if os.name == "nt":
        try:
            import csv
            import io
            import subprocess

            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=5,
            ).stdout
            for row in csv.reader(io.StringIO(out)):
                if len(row) >= 2 and row[0].lower() in WE_PROCESSES:
                    found.append((row[0].lower(), int(row[1])))
        except Exception as e:
            log.debug("tasklist failed: %s", e)
    _we_cache = (now, found)
    return found


def wallpaper_engine_running() -> bool:
    return bool(wallpaper_engine_processes())


def _process_exe(pid: int) -> Path | None:
    """Full path of a running process (works without admin rights)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return Path(buf.value)
        finally:
            k32.CloseHandle(handle)
    except Exception as e:
        log.debug("cannot read process path: %s", e)
    return None


def _steam_libraries() -> list[Path]:
    libs: list[Path] = []
    steam = None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except Exception:
        pass
    for base in filter(None, [steam, Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]):
        if base not in libs:
            libs.append(base)
        vdf = base / "steamapps" / "libraryfolders.vdf"
        try:
            for line in vdf.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith('"path"'):
                    lib = Path(line.split('"')[3].replace("\\\\", "\\"))
                    if lib not in libs:
                        libs.append(lib)
        except OSError:
            pass
    return libs


def wallpaper_engine_config_candidates() -> list[Path]:
    """Where config.json can be, best first: next to the running wallpaper64.exe."""
    candidates: list[Path] = []
    if os.environ.get("WALLPAPER_ENGINE_DIR"):
        candidates.append(Path(os.environ["WALLPAPER_ENGINE_DIR"]) / "config.json")
    for _name, pid in wallpaper_engine_processes():
        exe = _process_exe(pid)
        if exe is not None:
            # wallpaper64.exe lives in the install folder; older versions keep it in bin\
            candidates += [exe.parent / "config.json", exe.parent.parent / "config.json"]
    candidates += [lib / "steamapps" / "common" / "wallpaper_engine" / "config.json" for lib in _steam_libraries()]
    unique: list[Path] = []
    for c in candidates:
        if c not in unique:
            unique.append(c)
    return unique


def wallpaper_engine_config() -> Path | None:
    for cfg in wallpaper_engine_config_candidates():
        if cfg.is_file():
            return cfg
    return None


def _selected_files(node, inside: bool = False) -> list[tuple[str, str]]:
    """(monitor, file) of every entry under any "selectedwallpapers" block
    (the layout of config.json differs a little between Wallpaper Engine versions)."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            k = str(key).lower()
            if inside and isinstance(value, dict) and isinstance(value.get("file"), str):
                found.append((str(key), value["file"]))
            elif not (inside and k == "file"):
                found += _selected_files(value, inside or k == "selectedwallpapers")
    elif isinstance(node, list):
        for item in node:
            found += _selected_files(item, inside)
    return found


def _profiles(data: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """Wallpaper Engine keeps one block per user profile at the top of config.json.
    The current Windows user's profile goes first, so a stale profile never wins."""
    user = (os.environ.get("USERNAME") or "").lower()
    out = []
    for key, value in data.items() if isinstance(data, dict) else []:
        files = _selected_files(value)
        if files:
            out.append((str(key), files))
    out.sort(key=lambda kv: 0 if kv[0].lower() == user else 1)
    if not out:
        files = _selected_files(data)
        if files:
            out.append(("?", files))
    return out


def _monitor_order(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Primary monitor first ("Monitor0" / "\\\\?\\DISPLAY1..." sort first)."""
    return sorted(files, key=lambda mf: mf[0])


def _preview_for(file_value: str) -> Path | None:
    target = Path(file_value.replace("/", os.sep))
    if target.suffix.lower() in IMAGE_EXT and target.is_file():
        return target  # an image wallpaper: use it directly
    folder = target if target.is_dir() else target.parent
    project = folder / "project.json"
    try:
        preview = json.loads(project.read_text(encoding="utf-8-sig")).get("preview")
        if preview and (folder / preview).is_file():
            return folder / preview
    except (OSError, ValueError):
        pass
    for candidate in sorted(folder.glob("preview.*")):
        if candidate.suffix.lower() in IMAGE_EXT:
            return candidate
    return None


_we_logged: str | None = None


def wallpaper_engine_image() -> tuple[Path, Path] | None:
    """(preview image of the active wallpaper, config.json) when Wallpaper Engine is running."""
    global _we_logged
    if not wallpaper_engine_running():
        return None
    cfg = wallpaper_engine_config()
    if cfg is None:
        msg = "Wallpaper Engine is running but its config.json was not found"
        if _we_logged != msg:
            log.warning("%s (looked in: %s)", msg, ", ".join(map(str, wallpaper_engine_config_candidates())))
            _we_logged = msg
        return None
    try:
        data = json.loads(cfg.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None  # being rewritten right now: try again on the next poll
    for profile, files in _profiles(data):
        for monitor, file_value in _monitor_order(files):
            image = _preview_for(file_value)
            if image is not None:
                msg = f"Wallpaper Engine: profile {profile!r}, {monitor}: {image}"
                if _we_logged != msg:
                    log.info(msg)
                    _we_logged = msg
                return image, cfg
    msg = f"Wallpaper Engine: no preview image found in {cfg}"
    if _we_logged != msg:
        log.warning(msg)
        _we_logged = msg
    return None


def diagnose() -> int:
    """Print what the script sees, to paste back when colors don't follow the wallpaper."""
    print(f"config dir      : {CONFIG_DIR}")
    procs = wallpaper_engine_processes()
    print(f"WE processes    : {procs or 'none running'}")
    for _name, pid in procs:
        print(f"  pid {pid} exe : {_process_exe(pid)}")
    print("config.json candidates:")
    for c in wallpaper_engine_config_candidates():
        print(f"  [{'x' if c.is_file() else ' '}] {c}")
    cfg = wallpaper_engine_config()
    if cfg:
        try:
            data = json.loads(cfg.read_text(encoding="utf-8-sig"))
            print(f"top-level keys  : {list(data)[:12] if isinstance(data, dict) else type(data).__name__}")
            print(f"USERNAME        : {os.environ.get('USERNAME')}")
            for profile, files in _profiles(data):
                print(f"profile {profile!r}:")
                for monitor, f in _monitor_order(files):
                    print(f"  {monitor}: {f}\n      preview -> {_preview_for(f)}")
        except Exception as e:
            print(f"cannot read config.json: {e}")
    image, fp = current_source()
    print(f"SOURCE USED     : {fp[0]} -> {image}")
    try:
        cur = json.loads((CONFIG_DIR / "palette.json").read_text(encoding="utf-8"))
        print(f"palette.json    : source {cur.get('source')}, image {cur.get('image')}, bar {cur['palette']['bar']}")
    except Exception as e:
        print(f"palette.json    : {e}")
    return 0


def current_source() -> tuple[Path | None, tuple]:
    """Image to take colors from, plus a fingerprint that changes when it does."""
    we = wallpaper_engine_image()
    if we is not None:
        image, cfg = we
        return image, ("we", str(image), fingerprint(cfg), fingerprint(image))
    wp = current_wallpaper()
    return wp, ("windows", str(wp), fingerprint(wp) if wp else None)


def recolor(image: Path | None) -> None:
    data = None
    snapshot = None
    if image is not None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = CACHE_DIR / "wallpaper.img"  # TranscodedWallpaper has no extension
        try:
            shutil.copyfile(image, snapshot)
        except OSError as e:
            log.warning("cannot copy wallpaper: %s", e)
            snapshot = None
    if snapshot is not None:
        data = extract_with_pywal(snapshot) or extract_with_pillow(snapshot)
    if data is None:
        data = {**FALLBACK, "source": "fallback"}
    write_outputs(build_palette(data["bg"], data["candidates"]), data["source"], image)


_lock_handle = None


def _single_instance() -> bool:
    """Only one watcher at a time (setup may be run again)."""
    global _lock_handle
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _lock_handle = open(CACHE_DIR / "watch.lock", "a+")
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="recolor once and exit")
    ap.add_argument("--image", type=Path, help="use this image instead of the current wallpaper")
    ap.add_argument("--diagnose", action="store_true", help="print what the script detects and exit")
    args = ap.parse_args()
    if args.diagnose:
        return diagnose()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=CONFIG_DIR / "palette.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.once or args.image:
        recolor(args.image or current_source()[0])
        return 0

    if not _single_instance():
        log.info("watcher already running, exiting")
        return 0
    last = None
    while True:  # light polling: a couple of stat() calls every 2 s
        image, fp = current_source()
        if fp != last:
            time.sleep(0.8)  # let Windows / Wallpaper Engine finish writing
            image, fp = current_source()
            log.info("wallpaper changed (%s): %s", fp[0], image)
            try:
                recolor(image)
            except Exception:
                log.exception("recolor failed")
            last = fp
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
