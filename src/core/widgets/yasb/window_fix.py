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
from core.widgets.yasb import mint_health as health
from core.widgets.yasb.mint_common import process_name

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


GIVE_UP_LIMIT = 3  # cate incercari intr-o fereastra de timp inainte sa ne oprim
GIVE_UP_WINDOW = 10.0  # secunde


def keeps_undoing(recent: list[float], limit: int = GIVE_UP_LIMIT) -> bool:
    """Aplicatia isi pune fereastra la loc dupa fiecare corectie? Atunci nu are rost sa insistam."""
    return len(recent) >= limit


GUARD_GIVE_UP = 6  # cate reinregistrari incercam pentru aceeasi zona de lucru
GUARD_NAME = "window_fix paza"  # socoteala ei la mint_health, separata de corectarea ferestrelor


def keeps_refusing(fails: int, limit: int = GUARD_GIVE_UP) -> bool:
    """Windows nu da spatiul inapoi oricat insistam? Atunci ne oprim si asteptam o schimbare."""
    return fails >= limit


def mine_to_fix(window_monitor: int, bar_monitor: int) -> bool:
    """Fereastra e pe monitorul barei mele, adica a mea de corectat?

    Fiecare bara are propriul window_fix. Pana acum fiecare corecta orice fereastra din fata,
    oricare ar fi monitorul ei: cu trei bare, in jurnal se vede aceeasi fereastra mutata de noua
    ori intr-o secunda si trei randuri "nu mai incerc" in loc de unul (10-24, 10:52:40, nvidia
    app.exe). Si pragul de renuntare ajungea de trei ori mai mare decat cel scris in cod.

    Zero inseamna "nu se stie pe ce monitor": atunci nu refuzam nimic, ca pana acum.
    """
    if not window_monitor or not bar_monitor:
        return True
    return window_monitor == bar_monitor


def screen_alive(screen: object) -> bool:
    """Ecranul mai e al cui credem, sau Qt l-a sters deja (bare in reconstruire)?"""
    if screen is None:
        return False
    try:
        screen.devicePixelRatio()  # type: ignore[attr-defined]
    except RuntimeError:
        return False
    return True


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
        self._gave_up: set[int] = set()  # ferestre care isi pun geometria la loc: le lasam in pace
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
        health.connect(self._timer, "window_fix", self._check)
        self._timer.start()
        self._game_hwnd = 0  # fullscreen game the bar is hiding behind
        # one window_fix lives in every bar (one per monitor): each guards its own bar
        self._guard_next = 0.0
        self._guard_backoff = 2.0
        self._guard_fails = 0
        self._guard_area: tuple[Rect, Rect] | None = None  # zona de lucru de care e vorba
        if config.guard_reserved_space:
            self._guard_timer = QTimer(self)
            self._guard_timer.setInterval(1000)
            health.connect(self._guard_timer, GUARD_NAME, self._guard_reserved_space)
            self._guard_timer.start()

    def _process_name(self, hwnd: int) -> str:
        if hwnd in self._names:
            return self._names[hwnd]
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = process_name(pid.value)
        if len(self._names) > 200:
            self._names.clear()
        self._names[hwnd] = name
        return name

    def _guard_reserved_space(self) -> None:
        bar = self.window()
        flags = getattr(bar, "window_flags", None)
        manager = getattr(bar, "app_bar_manager", None)
        if bar is None or bar is self or not flags or not flags.get("windows_app_bar") or manager is None:
            return
        if not bar.isVisible():
            return  # hidden (auto-hide, fullscreen): nothing reserved on purpose
        if self._game_hwnd:
            return  # bara sta anume in spatele unei ferestre pe tot ecranul: atunci Windows ia zona de lucru
        screen = bar.screen()
        if not screen_alive(screen) or not screen_alive(getattr(bar, "target_screen", screen)):
            # Exact asta se vede in jurnal la 09:49:37, cand s-a schimbat un monitor: bar_manager
            # desfacea barele ("Screens updated. Re-initialising all bars"), iar paza, pornita la
            # fiecare secunda, ajungea la un ecran pe care Qt il stersese deja.
            return  # ecranele se refac; bara se reinregistreaza singura cand revine
        hwnd = int(bar.winId())
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self._user32.GetMonitorInfoW(self._user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
            return
        edge = getattr(bar, "alignment", {}).get("position", "top")
        dims = getattr(bar, "dimensions", {})
        pad = getattr(bar, "padding", {})
        logical = int(dims.get("height", 0)) + int(pad.get("top", 0)) + int(pad.get("bottom", 0))
        bar_px = round(logical * screen.devicePixelRatio())
        work, mon = _rect(info.rcWork), _rect(info.rcMonitor)
        now = time.monotonic()
        if not reservation_missing(edge, bar_px, work, mon):
            self._guard_backoff, self._guard_fails, self._guard_area = 2.0, 0, None
            return
        if self._guard_area != (work, mon):
            # Alta zona de lucru (un program a intrat sau a iesit din fullscreen, taskbar-ul s-a
            # mutat): situatie noua, se incearca de la capat, fara sa astepte rabatul de dinainte.
            # Dar nu chiar imediat: o zona care tot pleaca si vine ar scrie iar un rand pe secunda.
            self._guard_area = (work, mon)
            self._guard_backoff, self._guard_fails = 2.0, 0
            self._guard_next = min(self._guard_next, now + 2.0)
        if now < self._guard_next:
            return
        if keeps_refusing(self._guard_fails):
            return  # ne-am oprit pentru zona asta; reincercam cand se schimba ea
        self._guard_fails += 1
        # Un rand in jurnal, la prima incercare. Pana acum scriam unul la fiecare incercare: in
        # jurnalul tau sunt 100 de randuri identice, din minut in minut, de la 19:41 pana la capat.
        log = logging.warning if self._guard_fails == 1 else logging.debug
        log(
            "window_fix: Windows lost the space reserved for the bar (work %s, monitor %s): re-registering (%d/%d)",
            work,
            mon,
            self._guard_fails,
            GUARD_GIVE_UP,
        )
        # if something keeps undoing it, try less and less often (2 s ... 60 s)
        self._guard_next = now + self._guard_backoff
        self._guard_backoff = min(self._guard_backoff * 2, 60.0)
        try:
            manager.remove_appbar()
            bar.update_app_bar()
        except RuntimeError as exc:
            # bara a disparut intre masuratoare si reinregistrare: nu e greseala nimanui
            logging.debug("window_fix: nu mai e bara de reinregistrat (%s)", exc)
            return
        if keeps_refusing(self._guard_fails):
            logging.warning(
                "window_fix: nu pot lua inapoi locul barei dupa %d incercari; o las pana se schimba zona de lucru",
                GUARD_GIVE_UP,
            )

    def _check(self) -> None:
        try:
            self._check_foreground()
        except Exception as exc:
            health.failed("window_fix", exc, self._timer.stop)
        if self.config.hide_in_fullscreen_games:
            try:
                self._fullscreen_games()
            except Exception as exc:
                health.failed("window_fix", exc, self._timer.stop)

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

    def _bar_monitor(self) -> int:
        """Monitorul pe care sta bara mea; 0 daca nu se poate afla acum."""
        bar = self.window()
        if bar is None or bar is self:
            return 0
        try:
            return int(self._user32.MonitorFromWindow(int(bar.winId()), 2) or 0)
        except RuntimeError:
            return 0  # bara se reface; la trecerea urmatoare o gasim

    def _check_foreground(self) -> None:
        u = self._user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return
        hmon = int(u.MonitorFromWindow(hwnd, 2) or 0)
        if not mine_to_fix(hmon, self._bar_monitor()):
            return  # de fereastra asta se ocupa bara de pe monitorul ei
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
        if not u.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return
        args = (_rect(win), _rect(frame), _rect(info.rcWork), _rect(info.rcMonitor), self.config.tolerance)
        new, why = None, ""
        if fit_fullscreen:
            new, why = compute_fullscreen_fit(*args), "fullscreen below the bar"
        if new is None and fix_maximized:
            new, why = compute_fix(*args), "maximized inside the work area"
        if new is None:
            return
        if hwnd in self._gave_up:
            return
        now = time.monotonic()
        recent = [t for t in self._fixes.get(hwnd, []) if now - t < GIVE_UP_WINDOW]
        if keeps_undoing(recent, GIVE_UP_LIMIT):
            # Pana acum reincercam la nesfarsit, din 10 in 10 secunde. In jurnalul tau se vede
            # exact asta: Chrome isi punea fereastra la loc peste bara, de trei ori la fiecare
            # zece secunde, ore intregi. Daca nu se lasa, ne oprim si o spunem o data.
            self._gave_up.add(hwnd)
            logging.info("window_fix: %s isi pune fereastra la loc; nu mai incerc", name or hwnd)
            return
        recent.append(now)
        self._fixes[hwnd] = recent
        SWP_NOZORDER, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x0004, 0x0010, 0x0200
        l, t, r, b = new
        u.SetWindowPos(hwnd, None, l, t, r - l, b - t, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        logging.info("window_fix: %s -> %s %s", name or hwnd, why, new)
