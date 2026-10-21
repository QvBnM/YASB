"""
Mint Bar - functii comune pentru widget-urile noi (moduri, progres, notificari, accent...).

Nu e un widget: nu are clase BaseWidget, deci YASB nu il inregistreaza.
Tot ce e specific Windows se importa in interiorul functiilor, ca modulul
sa se poata incarca (si testa) si fara Windows.
"""

from __future__ import annotations

import colorsys
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

logger = logging.getLogger("mint")

# --------------------------------------------------------------------------- paleta

# Valorile Fuji din palette.css: folosite doar daca palette.css lipseste sau nu are variabila.
FALLBACK_PALETTE: dict[str, str] = {
    "bar": "#101716",
    "panel": "#121a19",
    "card": "#141d1c",
    "hover": "#1b2826",
    "line": "#2a3836",
    "track": "#243231",
    "dot": "#3a4846",
    "text": "#e6eceb",
    "text2": "#c9d3d1",
    "sub": "#7f908d",
    "muted": "#55615f",
    "on": "#0f1716",
    "accent": "#7dd9c7",
    "accent2": "#b9d4f0",
    "danger": "#e78a8a",
    "warn": "#e3c57f",
    "white": "#f2f5f4",
}

_VAR_RE = re.compile(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;")


def palette_path() -> str:
    try:
        from core.config import get_config_dir

        return os.path.join(get_config_dir(), "palette.css")
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".config", "yasb", "palette.css")


def parse_palette(css: str) -> dict[str, str]:
    """Citeste variabilele de culoare (#rrggbb) din textul unui palette.css."""
    out = dict(FALLBACK_PALETTE)
    for name, value in _VAR_RE.findall(css):
        out[name] = value.lower()
    # --warn lipseste din generatorul vechi: il derivam din accent si danger
    if "warn" not in dict(_VAR_RE.findall(css)):
        out["warn"] = FALLBACK_PALETTE["warn"]
    return out


def read_palette(path: str | None = None) -> dict[str, str]:
    path = path or palette_path()
    try:
        with open(path, encoding="utf-8") as f:
            return parse_palette(f.read())
    except OSError:
        return dict(FALLBACK_PALETTE)


# --------------------------------------------------------------------------- culori


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: Iterable[float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def luminance(h: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return rgb_to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def to_hls(h: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in hex_to_rgb(h))
    return colorsys.rgb_to_hls(r, g, b)


def from_hls(hh: float, ll: float, ss: float) -> str:
    r, g, b = colorsys.hls_to_rgb(hh, max(0.0, min(1.0, ll)), max(0.0, min(1.0, ss)))
    return rgb_to_hex((r * 255, g * 255, b * 255))


def ensure_contrast(fg: str, bg: str, min_ratio: float) -> tuple[str, float]:
    """
    Deschide (pe fundal inchis) sau inchide (pe fundal deschis) culoarea fg pana atinge
    contrastul minim fata de bg. Intoarce (culoarea, cat s-a schimbat luminozitatea 0..1).
    """
    if contrast(fg, bg) >= min_ratio:
        return fg, 0.0
    h, l0, s = to_hls(fg)
    step = 0.01 if luminance(bg) < 0.4 else -0.01
    l = l0
    for _ in range(100):
        l += step
        cand = from_hls(h, l, s)
        if contrast(cand, bg) >= min_ratio or l <= 0 or l >= 1:
            return cand, abs(l - l0)
    return from_hls(h, l, s), abs(l - l0)


# --------------------------------------------------------------------------- Qt


def all_bar_widgets(root=None):
    """Toate widget-urile YASB (BaseWidget) dintr-o bara, sau din toate barele."""
    from PyQt6.QtWidgets import QApplication

    from core.widgets.base import BaseWidget

    roots = [root] if root is not None else list(QApplication.topLevelWidgets())
    found = []
    for r in roots:
        if r is None:
            continue
        if isinstance(r, BaseWidget):
            found.append(r)
        found.extend(r.findChildren(BaseWidget))
    return found


def find_named(names: Iterable[str], root=None) -> list:
    """Widget-urile al caror nume din config.yaml (widget_name) e in `names`."""
    wanted = set(names)
    return [w for w in all_bar_widgets(root) if getattr(w, "widget_name", None) in wanted]


def set_class_token(widget, token: str, on: bool, prefix: str | None = None) -> bool:
    """Adauga / scoate o clasa CSS. Cu `prefix`, scoate intai toate clasele care incep asa."""
    from core.utils.utilities import refresh_widget_style

    current = (widget.property("class") or "").split()
    tokens = [t for t in current if not (prefix and t.startswith(prefix))]
    if on and token not in tokens:
        tokens.append(token)
    if not on and token in tokens:
        tokens.remove(token)
    if tokens != current:
        widget.setProperty("class", " ".join(tokens))
        refresh_widget_style(widget)
        return True
    return False


def refresh_tree(widget) -> None:
    from PyQt6.QtWidgets import QWidget

    from core.utils.utilities import refresh_widget_style

    refresh_widget_style(widget, *widget.findChildren(QWidget))


def make_invisible(widget) -> None:
    """Pentru widget-urile care doar lucreaza in fundal (ca window_fix)."""
    widget.setFixedSize(0, 0)
    widget.setVisible(False)


class PaletteWatcher:
    """Reciteste palette.css cand se schimba (la fiecare wallpaper) si anunta prin callback."""

    def __init__(self, parent, on_change):
        from PyQt6.QtCore import QFileSystemWatcher, QTimer

        self.path = palette_path()
        self.colors = read_palette(self.path)
        self._on_change = on_change
        self._watcher = QFileSystemWatcher(parent)
        if os.path.exists(self.path):
            self._watcher.addPath(self.path)
        self._watcher.fileChanged.connect(self._changed)
        # editorul / generatorul poate rescrie fisierul in doi pasi
        self._debounce = QTimer(parent)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._reload)

    def _changed(self, _path: str) -> None:
        self._debounce.start()

    def _reload(self) -> None:
        if os.path.exists(self.path) and self.path not in self._watcher.files():
            self._watcher.addPath(self.path)
        self.colors = read_palette(self.path)
        try:
            self._on_change(self.colors)
        except Exception:
            logger.exception("palette callback failed")


# --------------------------------------------------------------------------- Windows: fereastra activa


@dataclass
class Foreground:
    hwnd: int = 0
    pid: int = 0
    exe: str = ""
    title: str = ""
    fullscreen: bool = False


def foreground() -> Foreground:
    try:
        import ctypes
        from ctypes import wintypes

        import psutil

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return Foreground()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        try:
            exe = psutil.Process(pid.value).name()
        except Exception:
            exe = ""
        return Foreground(hwnd, pid.value, exe, buf.value, _is_fullscreen(hwnd))
    except Exception:
        return Foreground()


def _is_fullscreen(hwnd: int) -> bool:
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return False
    m = mi.rcMonitor
    return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom


def running_process_names() -> set[str]:
    try:
        import psutil

        return {(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
    except Exception:
        return set()


# --------------------------------------------------------------------------- Windows: cine foloseste microfonul

_MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _mic_app_name(key_name: str) -> str:
    # NonPackaged: "C:#Program Files#Discord#Discord.exe" ; packaged: "Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe"
    if "#" in key_name:
        base = key_name.split("#")[-1]
        return os.path.splitext(base)[0]
    return key_name.split("_")[0].split(".")[-1]


def mic_users(ignore: Iterable[str] = ()) -> list[str]:
    """
    Aplicatiile care folosesc microfonul acum. Windows tine evidenta pentru iconita din tray:
    o aplicatie cu LastUsedTimeStop = 0 (si Start > 0) inregistreaza chiar acum.
    """
    try:
        import winreg
    except ImportError:
        return []
    ignored = {i.lower() for i in ignore}
    users: list[str] = []

    def scan(key, path: str):
        try:
            with winreg.OpenKey(key, path) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    if sub == "NonPackaged":
                        scan(key, path + "\\NonPackaged")
                        continue
                    try:
                        with winreg.OpenKey(k, sub) as sk:
                            start = winreg.QueryValueEx(sk, "LastUsedTimeStart")[0]
                            stop = winreg.QueryValueEx(sk, "LastUsedTimeStop")[0]
                    except OSError:
                        continue
                    if start and not stop:
                        name = _mic_app_name(sub)
                        if name.lower() not in ignored:
                            users.append(name)
        except OSError:
            pass

    scan(winreg.HKEY_CURRENT_USER, _MIC_KEY)
    return users


# --------------------------------------------------------------------------- text


RO_MONTHS_SHORT = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "nov", "dec"]


def ro_day_month(d) -> str:
    return f"{d.day} {RO_MONTHS_SHORT[d.month - 1]}"


def ro_days(n: int) -> str:
    if n == 0:
        return "azi"
    if n == 1:
        return "mâine"
    # 1 zi, 2-19 zile, 20+ de zile
    return f"{n} zile" if (n % 100) < 20 else f"{n} de zile"


# --------------------------------------------------------------------------- etichete


_SPAN_SPLIT = re.compile(r"(<span.*?>.*?</span>)")


def fill_labels(widget, values: dict) -> None:
    """
    Completeaza etichetele construite cu build_widget_label (label sau label_alt, dupa caz).
    Textul si span-urile accepta acelasi format Python: "{fps:>3}", "<span>{icon}</span>".
    """
    show_alt = getattr(widget, "_show_alt_label", False)
    labels = widget._widgets_alt if show_alt else widget._widgets
    content = widget.config.label_alt if show_alt else widget.config.label
    parts = [p.strip() for p in _SPAN_SPLIT.split(content) if p and p.strip()]
    for label, part in zip(labels, parts):
        raw = re.sub(r"<span.*?>|</span>", "", part).strip() if "<span" in part else part
        try:
            text = raw.format(**values)
        except (KeyError, ValueError, IndexError):
            text = raw
        if label.text() != text:
            label.setText(text)


def toggle_alt(widget) -> None:
    widget._show_alt_label = not getattr(widget, "_show_alt_label", False)
    for lb in widget._widgets:
        lb.setVisible(not widget._show_alt_label)
    for lb in widget._widgets_alt:
        lb.setVisible(widget._show_alt_label)
