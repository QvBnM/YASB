"""
Network status for the bar: says plainly how the PC is connected (cable / Wi-Fi / offline),
whether a Wi-Fi card and a Bluetooth module exist at all, and runs a speed test, all inside
YASB (no external scripts).

Widgets:
  yasb.net_status.NetStatusWidget      icon in the bar + popup with connection, Wi-Fi, Bluetooth, speed test
  yasb.net_status.SpeedtestWidget      last speed test result in the bar; click = new test
  yasb.net_status.BluetoothAutoWidget  YASB's Bluetooth widget, hidden when the PC has no Bluetooth module

Everything is detected at runtime with Windows APIs (iphlpapi, wlanapi, BluetoothApis), so the
same config works on a desktop on cable and on a laptop with Wi-Fi and Bluetooth.
"""

import ctypes
import http.client
import json
import logging
import os
import re
import ssl
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.utils.qobject import is_valid_qobject
from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget
from core.validation.widgets.yasb.net_status import NetStatusConfig, SpeedtestConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb.bluetooth import BluetoothWidget

# ============================================================================ probes

IF_TYPE_ETHERNET = 6
IF_TYPE_WIFI = 71
IF_OPER_UP = 1
VIRTUAL_RE = re.compile(
    r"Hyper-V|Virtual|VMware|VirtualBox|TAP-|Wintun|WireGuard|Tailscale|ZeroTier|Npcap|Loopback|Bluetooth|Kernel Debug",
    re.I,
)


@dataclass
class Adapter:
    name: str
    description: str
    if_type: int
    up: bool
    gateway: bool
    speed_bps: int
    ipv4: str = ""

    @property
    def virtual(self) -> bool:
        return bool(VIRTUAL_RE.search(self.description) or VIRTUAL_RE.search(self.name))


@dataclass
class NetState:
    kind: str = "offline"  # "ethernet" | "wifi" | "offline"
    adapter: Adapter | None = None
    wifi: str = "none"  # "none" | "service_off" | "disconnected" | "connected"
    ssid: str = ""
    bluetooth: bool = False
    extra: dict = field(default_factory=dict)


if os.name == "nt":
    from ctypes import POINTER, Structure, byref, c_char_p, c_int, c_ubyte, c_uint32, c_uint64, c_void_p, c_wchar_p

    class _SOCKET_ADDRESS(Structure):
        _fields_ = [("lpSockaddr", c_void_p), ("iSockaddrLength", c_int)]

    class _UNICAST(Structure):
        pass

    _UNICAST._fields_ = [
        ("Length", c_uint32),
        ("Flags", c_uint32),
        ("Next", POINTER(_UNICAST)),
        ("Address", _SOCKET_ADDRESS),
    ]

    class _ADAPTER(Structure):
        pass

    # IP_ADAPTER_ADDRESSES_LH, only up to the fields we read (we walk the list through Next,
    # so the struct does not have to be complete).
    _ADAPTER._fields_ = [
        ("Length", c_uint32),
        ("IfIndex", c_uint32),
        ("Next", POINTER(_ADAPTER)),
        ("AdapterName", c_char_p),
        ("FirstUnicastAddress", POINTER(_UNICAST)),
        ("FirstAnycastAddress", c_void_p),
        ("FirstMulticastAddress", c_void_p),
        ("FirstDnsServerAddress", c_void_p),
        ("DnsSuffix", c_wchar_p),
        ("Description", c_wchar_p),
        ("FriendlyName", c_wchar_p),
        ("PhysicalAddress", c_ubyte * 8),
        ("PhysicalAddressLength", c_uint32),
        ("Flags", c_uint32),
        ("Mtu", c_uint32),
        ("IfType", c_uint32),
        ("OperStatus", c_int),
        ("Ipv6IfIndex", c_uint32),
        ("ZoneIndices", c_uint32 * 16),
        ("FirstPrefix", c_void_p),
        ("TransmitLinkSpeed", c_uint64),
        ("ReceiveLinkSpeed", c_uint64),
        ("FirstWinsServerAddress", c_void_p),
        ("FirstGatewayAddress", c_void_p),
    ]

    class _BT_FIND_RADIO_PARAMS(Structure):
        _fields_ = [("dwSize", c_uint32)]


def list_adapters() -> list[Adapter]:
    if os.name != "nt":
        return []
    iphlpapi = ctypes.WinDLL("iphlpapi")
    flags = 0x2 | 0x4 | 0x8 | 0x80  # skip anycast/multicast/dns, include gateways
    size = c_uint32(16 * 1024)
    for _ in range(4):
        buf = ctypes.create_string_buffer(size.value)
        rc = iphlpapi.GetAdaptersAddresses(0, flags, None, buf, byref(size))
        if rc == 0:
            break
        if rc != 111:  # ERROR_BUFFER_OVERFLOW: size was updated, try again
            return []
    else:
        return []
    out: list[Adapter] = []
    p = ctypes.cast(buf, POINTER(_ADAPTER))
    while p:
        a = p.contents
        ipv4 = ""
        u = a.FirstUnicastAddress
        while u:
            sa = u.contents.Address.lpSockaddr
            if sa and ctypes.c_ushort.from_address(sa).value == 2:  # AF_INET
                ipv4 = ".".join(str(b) for b in (ctypes.c_ubyte * 4).from_address(sa + 4))
                break
            u = u.contents.Next
        out.append(
            Adapter(
                name=a.FriendlyName or "",
                description=a.Description or "",
                if_type=a.IfType,
                up=a.OperStatus == IF_OPER_UP,
                gateway=bool(a.FirstGatewayAddress),
                speed_bps=int(a.ReceiveLinkSpeed or 0),
                ipv4=ipv4,
            )
        )
        p = a.Next
    return out


def wifi_status() -> tuple[str, str]:
    """("service_off" | "disconnected" | "connected" | "none", ssid) from the WLAN service."""
    if os.name != "nt":
        return "none", ""
    try:
        wlan = ctypes.WinDLL("wlanapi")
    except OSError:
        return "none", ""
    handle = c_void_p()
    negotiated = c_uint32()
    if wlan.WlanOpenHandle(2, None, byref(negotiated), byref(handle)) != 0:
        return "service_off", ""
    try:
        info = c_void_p()
        if wlan.WlanEnumInterfaces(handle, None, byref(info)) != 0 or not info:
            return "none", ""
        try:
            count = c_uint32.from_address(info.value).value
            if count == 0:
                return "none", ""
            state = "disconnected"
            ssid = ""
            for i in range(count):
                item = info.value + 8 + i * 532  # WLAN_INTERFACE_INFO: GUID(16) + WCHAR[256] + state
                if c_uint32.from_address(item + 528).value != 1:  # wlan_interface_state_connected
                    continue
                state = "connected"
                size = c_uint32()
                data = c_void_p()
                guid = ctypes.create_string_buffer(ctypes.string_at(item, 16), 16)
                rc = wlan.WlanQueryInterface(handle, guid, 7, None, byref(size), byref(data), None)
                if rc == 0 and data:
                    ssid = ctypes.wstring_at(data.value + 8)  # WLAN_CONNECTION_ATTRIBUTES.strProfileName
                    wlan.WlanFreeMemory(data)
                break
            return state, ssid
        finally:
            wlan.WlanFreeMemory(info)
    finally:
        wlan.WlanCloseHandle(handle, None)


def bluetooth_present() -> bool:
    if os.name != "nt":
        return False
    try:
        bt = ctypes.WinDLL("BluetoothApis")
    except OSError:
        return False
    bt.BluetoothFindFirstRadio.restype = c_void_p
    params = _BT_FIND_RADIO_PARAMS(4)
    radio = c_void_p()
    find = bt.BluetoothFindFirstRadio(byref(params), byref(radio))
    if not find:
        return False
    if radio:
        ctypes.windll.kernel32.CloseHandle(radio)
    bt.BluetoothFindRadioClose(c_void_p(find))
    return True


def pick_connection(adapters: list[Adapter]) -> Adapter | None:
    """The adapter carrying internet: up, with a gateway; real cards before virtual, cable before Wi-Fi."""
    live = [a for a in adapters if a.up and a.gateway and a.if_type in (IF_TYPE_ETHERNET, IF_TYPE_WIFI)]
    if not live:
        return None
    live.sort(key=lambda a: (a.virtual, a.if_type != IF_TYPE_ETHERNET))
    return live[0]


def probe(check_bluetooth: bool, last_bt: bool) -> NetState:
    adapters = list_adapters()
    st = NetState()
    conn = pick_connection(adapters)
    if conn is not None:
        st.adapter = conn
        st.kind = "wifi" if conn.if_type == IF_TYPE_WIFI else "ethernet"
    has_wifi_card = any(a.if_type == IF_TYPE_WIFI for a in adapters)
    if has_wifi_card:
        st.wifi, st.ssid = wifi_status()
        if st.wifi == "none":
            st.wifi = "disconnected"  # card is there but WLAN lists nothing yet
    else:
        st.wifi = "none"
    st.bluetooth = bluetooth_present() if check_bluetooth else last_bt
    return st


def format_speed(bps: int) -> str:
    if bps <= 0:
        return ""
    if bps >= 1_000_000_000:
        g = bps / 1_000_000_000
        return f"{g:.1f} Gbps".replace(".0 ", " ")
    return f"{bps / 1_000_000:.0f} Mbps"


def open_uri(uri: str) -> None:
    try:
        os.startfile(uri)  # type: ignore[attr-defined]
    except Exception:
        subprocess.Popen(["explorer.exe", uri])


# ======================================================================= speed test

CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "yasb-palette"
RESULT_FILE = CACHE_DIR / "speedtest.json"
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
                mins = f" (mai incearca peste ~{max(1, round(int(retry_after) / 60))} min)"
            msg = f"Cloudflare limiteaza testele: prea multe intr-o ora{mins}"
        else:
            msg = f"Cloudflare a refuzat cererea (HTTP {status})"
        super().__init__(msg)


def _conn(timeout: float = 15.0) -> http.client.HTTPConnection:
    if CF_SECURE:
        return http.client.HTTPSConnection(CF_HOST, timeout=timeout, context=ssl.create_default_context())
    return http.client.HTTPConnection(CF_HOST, timeout=timeout)


def _request(conn, method: str, path: str, body: bytes | None = None, sink=None) -> dict:
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
    return {"down": down, "up": up, "ping": ping, "server": f"Cloudflare {colo}".strip()}


def describe_error(e: Exception) -> str:
    text = str(e) or type(e).__name__
    if isinstance(e, ssl.SSLError):
        return f"SSL: {text}"
    if isinstance(e, TimeoutError):
        return "serverul nu a raspuns la timp"
    if isinstance(e, OSError) and getattr(e, "winerror", None) == 11001:
        return "fara internet (DNS)"
    return text


class SpeedRunner(QObject):
    """One shared speed test for every widget; results kept on disk between restarts."""

    changed = pyqtSignal()
    _instance: "SpeedRunner | None" = None

    @classmethod
    def instance(cls) -> "SpeedRunner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.running = False
        self.data: dict = {}
        try:
            self.data = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}
        if self.data.get("state") == "running":
            self.data = {}

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.changed.emit()
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            result = run_speedtest()
            data = {"state": "ok", **result, "finished": time.time()}
        except Exception as e:
            logging.warning("Speed test failed: %s", e)
            data = {"state": "error", "error": describe_error(e), "finished": time.time()}
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            RESULT_FILE.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
        self.data = data
        self.running = False
        self.changed.emit()  # queued to the GUI thread

    def texts(self) -> dict[str, str]:
        """{result, down, up, ping, time, tooltip, detail} for labels and the popup."""
        d = self.data
        if self.running:
            return {
                "result": "testez…",
                "down": "",
                "up": "",
                "ping": "testez…",
                "time": "",
                "tooltip": "Testul rulează (cam 15 secunde)",
                "detail": "Testez download, upload și ping… (cam 15 secunde)",
            }
        if d.get("state") == "ok":
            when = time.strftime("%H:%M", time.localtime(d.get("finished", time.time())))
            return {
                "result": f"↓{d['down']:.0f} ↑{d['up']:.0f}",
                "down": f"{d['down']:.0f}",
                "up": f"{d['up']:.0f}",
                "ping": f"{d['ping']:.0f} ms",
                "time": when,
                "tooltip": f"Download {d['down']:.1f} Mbps\nUpload {d['up']:.1f} Mbps\nPing {d['ping']:.0f} ms\n"
                f"Server: {d.get('server', '?')}\nTestat la {when}. Click pentru un test nou.",
                "detail": f"↓ {d['down']:.0f} Mbps   ↑ {d['up']:.0f} Mbps   ping {d['ping']:.0f} ms   ({when})",
            }
        if d.get("state") == "error":
            return {
                "result": "eroare",
                "down": "",
                "up": "",
                "ping": "eroare",
                "time": "",
                "tooltip": f"Testul a eșuat: {d.get('error', '?')}\nClick pentru a reîncerca.",
                "detail": f"Testul a eșuat: {d.get('error', '?')}",
            }
        return {
            "result": "test",
            "down": "",
            "up": "",
            "ping": "click = test",
            "time": "",
            "tooltip": "Click pentru un test de viteză (Cloudflare, ~15 s)",
            "detail": "Niciun test încă.",
        }


# ========================================================================= widgets


def _fill(widgets: list[QLabel], template: str, values: dict[str, str]) -> None:
    parts = [p for p in re.split(r"(<span.*?>.*?</span>)", template) if p and p.strip()]
    for i, part in enumerate(parts):
        if i >= len(widgets):
            break
        text = re.sub(r"<span.*?>|</span>", "", part).strip() if "<span" in part else part.strip()
        for k, v in values.items():
            text = text.replace("{" + k + "}", v)
        widgets[i].setText(text)


class _LabelWidget(BaseWidget):
    def _setup_labels(self, label: str, label_alt: str) -> None:
        self._show_alt = False
        self._label_tpl = label
        self._label_alt_tpl = label_alt
        self._init_container()
        self.build_widget_label(label, label_alt)
        self.register_callback("toggle_label", self._toggle_label)

    def _toggle_label(self) -> None:
        self._show_alt = not self._show_alt
        for w in self._widgets:
            w.setVisible(not self._show_alt)
        for w in self._widgets_alt:
            w.setVisible(self._show_alt)
        self._render()

    def _set_labels(self, values: dict[str, str]) -> None:
        if self._show_alt:
            _fill(self._widgets_alt, self._label_alt_tpl, values)
        else:
            _fill(self._widgets, self._label_tpl, values)

    def _render(self) -> None:  # overridden
        pass


class SpeedtestWidget(_LabelWidget):
    validation_schema = SpeedtestConfig

    def __init__(self, config: SpeedtestConfig):
        super().__init__(class_name=f"speedtest-widget {config.class_name}")
        self.config = config
        self._setup_labels(config.label, config.label_alt)
        self.register_callback("run_test", self._run_test)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        self._runner = SpeedRunner.instance()
        self._runner.changed.connect(self._render)
        self._render()

    def _run_test(self) -> None:
        self._runner.start()

    def _render(self) -> None:
        if not is_valid_qobject(self):
            return
        t = self._runner.texts()
        self._set_labels(t)
        state = "running" if self._runner.running else self._runner.data.get("state", "idle")
        self.setProperty("state", state)
        if self.config.tooltip:
            set_tooltip(self, t["tooltip"])


class NetStatusWidget(_LabelWidget):
    validation_schema = NetStatusConfig

    def __init__(self, config: NetStatusConfig):
        super().__init__(class_name=f"net-status-widget {config.class_name}")
        self.config = config
        self._state = NetState()
        self._bt_checked_at = 0.0
        self._menu: PopupWidget | None = None
        self._menu_refs: dict[str, QLabel | QPushButton] = {}
        self._setup_labels(config.label, config.label_alt)
        self.register_callback("toggle_menu", self._toggle_menu)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        self._runner = SpeedRunner.instance()
        self._runner.changed.connect(self._refresh_menu)

        self._timer = QTimer(self)
        self._timer.setInterval(config.update_interval)
        self._timer.timeout.connect(self._update)
        self._timer.start()
        self._update()

    # ------------------------------------------------------------------ state

    def _update(self) -> None:
        now = time.monotonic()
        check_bt = now - self._bt_checked_at > 30 or self._bt_checked_at == 0
        try:
            self._state = probe(check_bt, self._state.bluetooth)
        except Exception as e:
            logging.debug("net_status probe failed: %s", e)
            return
        if check_bt:
            self._bt_checked_at = now
        self._render()
        self._refresh_menu()

    def _summary(self) -> dict[str, str]:
        s, ic = self._state, self.config.icons
        a = s.adapter
        if s.kind == "ethernet":
            icon, name, title = ic.ethernet, "Cablu", "Conectat prin cablu (Ethernet)"
        elif s.kind == "wifi":
            icon, name, title = ic.wifi, s.ssid or "Wi-Fi", f"Conectat prin Wi-Fi: {s.ssid or 'rețea'}"
        else:
            icon, name, title = ic.offline, "Offline", "Fără conexiune la internet"
        return {
            "icon": icon,
            "name": name,
            "title": title,
            "ip": a.ipv4 if a else "",
            "speed": format_speed(a.speed_bps) if a else "",
            "adapter": a.description if a else "",
        }

    def _wifi_text(self) -> tuple[str, str]:
        s = self._state
        if s.wifi == "none":
            return "Nu ai placă Wi-Fi", ""
        if s.wifi == "service_off":
            return "Placa există, dar serviciul WLAN e oprit", ""
        if s.wifi == "connected":
            return f"Conectat la {s.ssid or 'o rețea'}", "Rețele"
        return "Pornit, neconectat", "Alege o rețea"

    def _render(self) -> None:
        if not is_valid_qobject(self):
            return
        v = self._summary()
        self._set_labels(v)
        self.setProperty("kind", self._state.kind)
        if self.config.tooltip:
            extra = " · ".join(x for x in (v["speed"], v["ip"]) if x)
            set_tooltip(self, v["title"] + (f"\n{extra}" if extra else ""))

    # ------------------------------------------------------------------- menu

    def _toggle_menu(self) -> None:
        if self._menu is not None and is_valid_qobject(self._menu) and self._menu.isVisible():
            self._menu.hide()
            return
        self._show_menu()

    def _row(self, parent_layout: QVBoxLayout, key: str, icon: str, title: str) -> None:
        row = QFrame()
        row.setProperty("class", "row")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        ic = QLabel(icon)
        ic.setProperty("class", "row-icon")
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        text = QVBoxLayout()
        text.setSpacing(1)
        t = QLabel(title)
        t.setProperty("class", "row-title")
        val = QLabel("")
        val.setProperty("class", "row-value")
        val.setWordWrap(True)
        text.addWidget(t)
        text.addWidget(val)
        lay.addLayout(text, 1)
        btn = QPushButton("")
        btn.setProperty("class", "row-button")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        parent_layout.addWidget(row)
        self._menu_refs[key + "_icon"] = ic
        self._menu_refs[key + "_value"] = val
        self._menu_refs[key + "_button"] = btn

    def _show_menu(self) -> None:
        m = self.config.menu
        ic = self.config.icons
        self._menu = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        self._menu.setProperty("class", "net-status-menu")
        self._menu_refs = {}
        root = QVBoxLayout(self._menu)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QLabel("Rețea")
        header.setProperty("class", "header")
        root.addWidget(header)

        body = QFrame()
        body.setProperty("class", "body")
        bl = QVBoxLayout(body)
        bl.setSpacing(12)
        self._row(bl, "conn", ic.ethernet, "Conexiune")
        self._row(bl, "wifi", ic.wifi, "Wi-Fi")
        self._row(bl, "bt", ic.bluetooth, "Bluetooth")
        if m.show_speedtest:
            self._row(bl, "speed", ic.speed, "Test de viteză")
        root.addWidget(body)

        footer = QFrame()
        footer.setProperty("class", "footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(0, 0, 0, 0)
        settings = QPushButton("Setări rețea")
        settings.setProperty("class", "settings-button")
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.clicked.connect(lambda: self._open("ms-settings:network"))
        fl.addWidget(settings)
        fl.addStretch()
        root.addWidget(footer)

        self._menu_refs["conn_button"].clicked.connect(lambda: self._open("ms-settings:network-status"))
        self._menu_refs["wifi_button"].clicked.connect(lambda: self._open("ms-availablenetworks:"))
        self._menu_refs["bt_button"].clicked.connect(lambda: self._open("ms-settings:bluetooth"))
        if m.show_speedtest:
            self._menu_refs["speed_button"].clicked.connect(lambda: self._runner.start())

        self._refresh_menu()
        self._menu.adjustSize()
        self._menu.setPosition(
            alignment=m.alignment, direction=m.direction, offset_left=m.offset_left, offset_top=m.offset_top
        )
        self._menu.show()

    def _open(self, uri: str) -> None:
        open_uri(uri)
        if self._menu is not None and is_valid_qobject(self._menu):
            self._menu.hide()

    def _set_row(self, key: str, value: str, button: str, icon: str | None = None, state: str = "") -> None:
        val = self._menu_refs.get(key + "_value")
        btn = self._menu_refs.get(key + "_button")
        ico = self._menu_refs.get(key + "_icon")
        if val is None or not is_valid_qobject(val):
            return
        val.setText(value)
        btn.setText(button)
        btn.setVisible(bool(button))
        if icon is not None:
            ico.setText(icon)
        if ico.property("state") != state:
            ico.setProperty("state", state)
            ico.style().unpolish(ico)
            ico.style().polish(ico)

    def _refresh_menu(self) -> None:
        if self._menu is None or not is_valid_qobject(self._menu) or not self._menu_refs:
            return
        s, ic = self._state, self.config.icons
        v = self._summary()
        details = " · ".join(x for x in (v["speed"], v["ip"]) if x)
        conn_text = v["title"] + (f"\n{details}" if details else "")
        if s.kind == "offline":
            conn_text += "\nVerifică cablul sau routerul."
        self._set_row("conn", conn_text, "Detalii", v["icon"], "on" if s.kind != "offline" else "off")

        wifi_text, wifi_btn = self._wifi_text()
        wifi_icon = ic.wifi if s.wifi in ("connected", "disconnected") else ic.wifi_off
        self._set_row("wifi", wifi_text, wifi_btn, wifi_icon, "on" if s.wifi == "connected" else "off")

        if s.bluetooth:
            self._set_row("bt", "Disponibil", "Dispozitive", ic.bluetooth, "on")
        else:
            self._set_row("bt", "Nu ai modul Bluetooth", "", ic.bluetooth_off, "off")

        if self.config.menu.show_speedtest:
            t = self._runner.texts()
            btn = "" if self._runner.running else ("Testează din nou" if self._runner.data else "Pornește testul")
            self._set_row("speed", t["detail"], btn, None, "on" if self._runner.data.get("state") == "ok" else "")
        if is_valid_qobject(self._menu):
            self._menu.adjustSize()


class BluetoothAutoWidget(BluetoothWidget):
    """YASB's Bluetooth widget, but invisible when the PC has no Bluetooth module."""

    def __init__(self, config):
        self._has_radio = bluetooth_present() if os.name == "nt" else True
        super().__init__(config)
        self.setVisible(True)
        self._radio_timer = QTimer(self)
        self._radio_timer.setInterval(30_000)
        self._radio_timer.timeout.connect(self._check_radio)
        self._radio_timer.start()

    def _check_radio(self) -> None:
        has = bluetooth_present()
        if has != self._has_radio:
            self._has_radio = has
            self.setVisible(True)

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt API)
        super().setVisible(visible and getattr(self, "_has_radio", True))
