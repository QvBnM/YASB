"""
Keeps maximized windows inside the work area.

Some apps draw their own title bar (Discord, qBittorrent, other Electron / custom-frame apps).
When a second app bar (this bar) reserves space at the top, they put the window just below the
bar but keep the height of the whole screen minus the taskbar, so their bottom edge slides under
the taskbar. Normal windows already fit and are never touched.

This invisible widget watches the foreground window; if it is maximized and its visible frame
sticks out of the monitor's work area, it is moved back to exactly the work area (the window's
invisible resize borders are kept, so it looks like a normal maximized window).
"""

import ctypes
import logging
import os
import time
from ctypes import wintypes

from PyQt6.QtCore import QTimer

from core.validation.widgets.yasb.window_fix import WindowFixConfig
from core.widgets.base import BaseWidget

Rect = tuple[int, int, int, int]  # left, top, right, bottom


def compute_fix(window: Rect, frame: Rect, work: Rect, monitor: Rect, tolerance: int = 2) -> Rect | None:
    """New window rect that puts the visible frame exactly on the work area, or None if it already fits.

    window  = GetWindowRect (includes the invisible resize borders)
    frame   = DWM extended frame bounds (what you see)
    work    = monitor work area (screen minus taskbar and app bars)
    monitor = whole monitor
    """
    fl, ft, fr, fb = frame
    wl, wt, wr, wb = work
    # a real fullscreen window (video, game) covers the whole monitor on purpose: leave it
    if frame == monitor:
        return None
    sticks_out = fl < wl - tolerance or ft < wt - tolerance or fr > wr + tolerance or fb > wb + tolerance
    if not sticks_out:
        return None
    # keep the invisible borders the window has around its visible frame
    ml, mt = fl - window[0], ft - window[1]
    mr, mb = window[2] - fr, window[3] - fb
    return (wl - ml, wt - mt, wr + mr, wb + mb)


def compute_fullscreen_fit(window: Rect, frame: Rect, work: Rect, monitor: Rect, tolerance: int = 2) -> Rect | None:
    """Fullscreen window (covers the whole monitor) moved to start below a top bar; None if not needed.

    The bar's reserved strip is work.top - monitor.top. The bottom stays at the monitor's edge:
    in fullscreen the taskbar is hidden anyway.
    """
    top_strip = work[1] - monitor[1]
    if top_strip <= 0:
        return None  # no bar reserved at the top of this monitor
    fl, ft, fr, fb = frame
    ml, mt, mr, mb = monitor
    covers = fl <= ml + tolerance and ft <= mt + tolerance and fr >= mr - tolerance and fb >= mb - tolerance
    if not covers:
        return None
    ol, ot = fl - window[0], ft - window[1]
    or_, ob = window[2] - fr, window[3] - fb
    return (ml - ol, mt + top_strip - ot, mr + or_, mb + ob)


SHELL_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "XamlExplorerHostIslandWindow",
    "Windows.UI.Core.CoreWindow",  # touch keyboard / emoji panel, Start, Search: full-screen but invisible
}
SHELL_PROCESSES = {
    "textinputhost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "searchhost.exe",
    "searchapp.exe",
    "lockapp.exe",
    "explorer.exe",
}


def covers_monitor(frame: Rect, monitor: Rect, tolerance: int = 2) -> bool:
    fl, ft, fr, fb = frame
    ml, mt, mr, mb = monitor
    return fl <= ml + tolerance and ft <= mt + tolerance and fr >= mr - tolerance and fb >= mb - tolerance


def is_fullscreen_game(
    process: str, window_class: str, own: bool, frame: Rect, monitor: Rect, keep_bar: set[str]
) -> bool:
    """A fullscreen window the bar should step behind: not the desktop/shell, not ours, not a browser/player."""
    if own or window_class in SHELL_CLASSES or process.lower() in keep_bar or process.lower() in SHELL_PROCESSES:
        return False
    return covers_monitor(frame, monitor)


def process_name_from_pid(pid: int) -> str:
    """exe name of a process with plain Win32 (psutil is no longer installed with YASB)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value)
    finally:
        k32.CloseHandle(handle)


def reservation_missing(edge: str, bar_px: int, work: Rect, monitor: Rect, tolerance: int = 2) -> bool:
    """True when the monitor's work area no longer leaves room for a bar of bar_px on its edge."""
    if bar_px <= 0:
        return False
    if edge == "top":
        return work[1] - monitor[1] < bar_px - tolerance
    return monitor[3] - work[3] < bar_px - tolerance


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _rect(r: wintypes.RECT) -> Rect:
    return (r.left, r.top, r.right, r.bottom)


class WindowFixWidget(BaseWidget):
    validation_schema = WindowFixConfig

    def __init__(self, config: WindowFixConfig):
        super().__init__(class_name=f"window-fix-widget {config.class_name}")
        self.config = config
        self.setFixedSize(0, 0)
        self.hide()
        self._only = {p.lower() for p in config.processes}
        self._exclude = {p.lower() for p in config.exclude}
        self._fullscreen_fit = {p.lower() for p in config.fullscreen_fit}
        self._fixes: dict[int, list[float]] = {}  # hwnd -> times corrected (stop if an app fights back)
        self._names: dict[int, str] = {}
        if os.name != "nt":
            return
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._dwm = ctypes.WinDLL("dwmapi")
        self._user32.MonitorFromWindow.restype = wintypes.HMONITOR
        self._user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self._user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        self._timer = QTimer(self)
        self._timer.setInterval(config.interval)
        self._timer.timeout.connect(self._check)
        self._timer.start()
        self._game_hwnd = 0  # fullscreen game the bar is hiding behind
        # one window_fix lives in every bar (one per monitor): each guards its own bar
        self._guard_next = 0.0
        self._guard_backoff = 2.0
        if config.guard_reserved_space:
            self._guard_timer = QTimer(self)
            self._guard_timer.setInterval(1000)
            self._guard_timer.timeout.connect(self._guard)
            self._guard_timer.start()

    def _process_name(self, hwnd: int) -> str:
        if hwnd in self._names:
            return self._names[hwnd]
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = process_name_from_pid(pid.value)
        if len(self._names) > 200:
            self._names.clear()
        self._names[hwnd] = name
        return name

    def _guard(self) -> None:
        try:
            self._guard_reserved_space()
        except Exception as e:
            logging.debug("window_fix guard: %s", e)

    def _guard_reserved_space(self) -> None:
        bar = self.window()
        flags = getattr(bar, "window_flags", None)
        manager = getattr(bar, "app_bar_manager", None)
        if bar is None or bar is self or not flags or not flags.get("windows_app_bar") or manager is None:
            return
        if not bar.isVisible():
            return  # hidden (auto-hide, fullscreen): nothing reserved on purpose
        now = time.monotonic()
        if now < self._guard_next:
            return
        hwnd = int(bar.winId())
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self._user32.GetMonitorInfoW(self._user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
            return
        edge = getattr(bar, "alignment", {}).get("position", "top")
        dims = getattr(bar, "dimensions", {})
        pad = getattr(bar, "padding", {})
        logical = int(dims.get("height", 0)) + int(pad.get("top", 0)) + int(pad.get("bottom", 0))
        bar_px = round(logical * bar.screen().devicePixelRatio()) if bar.screen() else logical
        work, mon = _rect(info.rcWork), _rect(info.rcMonitor)
        if not reservation_missing(edge, bar_px, work, mon):
            self._guard_backoff = 2.0
            return
        logging.warning(
            "window_fix: Windows lost the space reserved for the bar (work %s, monitor %s): re-registering", work, mon
        )
        try:
            manager.remove_appbar()
            bar.update_app_bar()
        except Exception:
            logging.exception("window_fix: re-registering the bar failed")
        # if something keeps undoing it, try less and less often (2 s ... 60 s)
        self._guard_next = now + self._guard_backoff
        self._guard_backoff = min(self._guard_backoff * 2, 60.0)

    def _check(self) -> None:
        try:
            self._check_foreground()
        except Exception as e:
            logging.debug("window_fix: %s", e)
        if self.config.hide_in_fullscreen_games:
            try:
                self._fullscreen_games()
            except Exception as e:
                logging.debug("window_fix games: %s", e)

    def _window_info(self, hwnd: int) -> tuple[Rect, Rect, int]:
        """(visible frame, monitor rect, monitor handle) of a window."""
        u = self._user32
        frame = wintypes.RECT()
        if self._dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(frame), ctypes.sizeof(frame)) != 0:
            u.GetWindowRect(hwnd, ctypes.byref(frame))
        hmon = u.MonitorFromWindow(hwnd, 2)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        u.GetMonitorInfoW(hmon, ctypes.byref(info))
        return _rect(frame), _rect(info.rcMonitor), int(hmon or 0)

    def _cloaked(self, hwnd: int) -> bool:
        """Windows hides some windows without un-showing them (DWM "cloaked"): they cover nothing."""
        value = ctypes.c_int(0)
        if self._dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            return False
        return value.value != 0

    def _set_bar_z(self, bar_hwnd: int, on_top: bool) -> None:
        HWND_TOPMOST, HWND_BOTTOM = -1, 1
        flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
        self._user32.SetWindowPos(bar_hwnd, HWND_TOPMOST if on_top else HWND_BOTTOM, 0, 0, 0, 0, flags)

    def _fullscreen_games(self) -> None:
        bar = self.window()
        if bar is None or bar is self:
            return
        u = self._user32
        bar_hwnd = int(bar.winId())
        bar_mon = int(u.MonitorFromWindow(bar_hwnd, 2) or 0)
        game = self._game_hwnd
        if game:
            still = u.IsWindow(game) and u.IsWindowVisible(game) and not u.IsIconic(game) and not self._cloaked(game)
            if still:
                frame, mon, hmon = self._window_info(game)
                still = hmon == bar_mon and covers_monitor(frame, mon)
            if still:
                return  # keep hiding behind it, even while you click on another monitor
            self._game_hwnd = 0
            self._set_bar_z(bar_hwnd, True)
            logging.info("window_fix: fullscreen ended, bar back on top")
            return
        fg = u.GetForegroundWindow()
        if not fg or self._cloaked(fg):
            return
        frame, mon, hmon = self._window_info(fg)
        if hmon != bar_mon:
            return
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        cls = ctypes.create_unicode_buffer(128)
        u.GetClassNameW(fg, cls, 128)
        name = self._process_name(fg)
        if is_fullscreen_game(name, cls.value, pid.value == os.getpid(), frame, mon, self._fullscreen_fit):
            self._game_hwnd = int(fg)
            self._set_bar_z(bar_hwnd, False)
            logging.info("window_fix: %s is fullscreen, bar goes behind it", name or fg)

    def _check_foreground(self) -> None:
        u = self._user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return
        zoomed = bool(u.IsZoomed(hwnd))
        name = self._process_name(hwnd).lower()
        if name in self._exclude:
            return
        fit_fullscreen = name in self._fullscreen_fit
        fix_maximized = zoomed and (not self._only or name in self._only)
        if not (fit_fullscreen or fix_maximized):
            return
        win = wintypes.RECT()
        frame = wintypes.RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(win)):
            return
        if self._dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(frame), ctypes.sizeof(frame)) != 0:
            frame = win  # DWMWA_EXTENDED_FRAME_BOUNDS unavailable
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
            return
        args = (_rect(win), _rect(frame), _rect(info.rcWork), _rect(info.rcMonitor), self.config.tolerance)
        new, why = None, ""
        if fit_fullscreen:
            new, why = compute_fullscreen_fit(*args), "fullscreen below the bar"
        if new is None and fix_maximized:
            new, why = compute_fix(*args), "maximized inside the work area"
        if new is None:
            return
        now = time.monotonic()
        recent = [t for t in self._fixes.get(hwnd, []) if now - t < 10]
        if len(recent) >= 3:
            return  # the app keeps undoing it: don't fight
        recent.append(now)
        self._fixes[hwnd] = recent
        SWP_NOZORDER, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x0004, 0x0010, 0x0200
        l, t, r, b = new
        u.SetWindowPos(hwnd, None, l, t, r - l, b - t, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        logging.info("window_fix: %s -> %s %s", name or hwnd, why, new)
