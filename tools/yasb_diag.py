"""
yasb_diag.py - what Windows sees around the bar (monitors, reserved space, big windows).

    py -3.14 yasb_diag.py              # print the report
    py -3.14 yasb_diag.py --wait 5     # wait 5 s first (time to click Chrome / go fullscreen)

Read-only: it changes nothing. Coordinates are physical pixels.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
shell32 = ctypes.WinDLL("shell32")
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: physical pixels
except Exception:
    pass

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x8
WS_EX_TOOLWINDOW = 0x80


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
shell32.SHAppBarMessage.restype = ctypes.c_size_t
shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]


def r(rc: wintypes.RECT) -> str:
    return f"({rc.left},{rc.top})-({rc.right},{rc.bottom}) {rc.right - rc.left}x{rc.bottom - rc.top}"


def monitors() -> list[tuple[int, MONITORINFOEXW, int]]:
    out = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rc, _lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        dpi = 96
        try:
            x, y = wintypes.UINT(), wintypes.UINT()
            ctypes.WinDLL("shcore").GetDpiForMonitor(hmon, 0, ctypes.byref(x), ctypes.byref(y))
            dpi = x.value
        except Exception:
            pass
        out.append((hmon, mi, dpi))
        return True

    user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return out


def proc_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid.value)
    name = ""
    if h:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            name = os.path.basename(buf.value)
        k32.CloseHandle(h)
    return f"{name or '?'} (pid {pid.value})"


def title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value[:60]


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def frame(hwnd: int) -> wintypes.RECT:
    rc = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rc), ctypes.sizeof(rc)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return rc


def top_windows() -> list[int]:
    hs: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _lp):
        hs.append(int(h))
        return True

    user32.EnumWindows(proc(cb), 0)
    return hs  # z-order: first = top


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=0)
    a = ap.parse_args()
    if a.wait:
        print(f"Astept {a.wait:.0f} s: da click pe Chrome (sau pune-l in fullscreen)...")
        time.sleep(a.wait)

    print("=== MONITOARE (rcWork = spatiul lasat ferestrelor) ===")
    mons = monitors()
    for i, (_h, mi, dpi) in enumerate(mons):
        m, w = mi.rcMonitor, mi.rcWork
        print(f"[{i}] {mi.szDevice} {'PRINCIPAL ' if mi.dwFlags & 1 else ''}scalare {dpi * 100 // 96}%")
        print(f"    monitor: {r(m)}")
        print(f"    work   : {r(w)}")
        print(f"    rezervat: sus {w.top - m.top}px, jos {m.bottom - w.bottom}px, stanga {w.left - m.left}px, dreapta {m.right - w.right}px")
        if w.top == m.top:
            print("    !!! sus NU e rezervat nimic -> ferestrele maximizate intra sub bara")

    print("\n=== TASKBAR ===")
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(abd)
    state = shell32.SHAppBarMessage(4, ctypes.byref(abd))  # ABM_GETSTATE
    shell32.SHAppBarMessage(5, ctypes.byref(abd))  # ABM_GETTASKBARPOS
    edges = {0: "stanga", 1: "SUS", 2: "dreapta", 3: "jos"}
    print(f"autohide: {'DA' if state & 1 else 'nu'} | margine: {edges.get(abd.uEdge, abd.uEdge)} | {r(abd.rc)}")

    bars = [h for h in top_windows() if title(h) == "YasbBar"]
    print(f"\n=== YASB: {len(bars)} ferestre de bara gasite" + ("" if bars else " -> YASB nu ruleaza sau nu a creat bara") + " ===")
    print("\n=== FERESTRE (de sus in jos, in ordinea de pe ecran) ===")
    fg = user32.GetForegroundWindow()
    shown = 0
    for h in top_windows():
        if not user32.IsWindowVisible(h) or user32.IsIconic(h):
            continue
        name = proc_name(h)
        rc = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(rc))
        fr = frame(h)
        ex = user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
        hmon = user32.MonitorFromWindow(h, 2)
        mi = next((m for hm, m, _d in mons if hm == hmon), None)
        if mi is None:
            continue
        m = mi.rcMonitor
        width, height = fr.right - fr.left, fr.bottom - fr.top
        is_bar = title(h) == "YasbBar" or ("python" in name.lower() and height <= 120 and width >= (m.right - m.left) * 0.5)
        zoomed = bool(user32.IsZoomed(h))
        covers = fr.left <= m.left and fr.top <= m.top and fr.right >= m.right and fr.bottom >= m.bottom
        if not (is_bar or zoomed or covers or h == fg):
            continue
        tags = []
        if is_bar:
            tags.append("BARA YASB")
        if zoomed:
            tags.append("maximizata")
        if covers:
            tags.append("acopera tot monitorul")
        if h == fg:
            tags.append("ACTIVA")
        tags.append("TOPMOST" if ex & WS_EX_TOPMOST else "normala")
        cloak = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(cloak), ctypes.sizeof(cloak))
        if cloak.value:
            tags.append("ascunsa de Windows (cloaked)")
        print(f"- {name} | {class_name(h)} | \"{title(h)}\"")
        print(f"    {' / '.join(tags)}")
        print(f"    fereastra: {r(rc)}")
        print(f"    vizibil  : {r(fr)}   (monitor {mi.szDevice}, work sus={mi.rcWork.top})")
        if zoomed and not is_bar and fr.top < mi.rcWork.top - 2:
            print("    !!! maximizata dar incepe mai sus decat spatiul liber -> e sub bara")
        shown += 1
        if shown >= 14:
            break

    log = Path(os.environ.get("YASB_CONFIG_HOME") or Path.home() / ".config" / "yasb") / "yasb.log"
    print(f"\n=== {log} (window_fix / AppBar / erori, ultimele 25) ===")
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        keep = [ln for ln in lines if any(k in ln for k in ("window_fix", "AppBar", "ERROR", "Error", "fullscreen", "Traceback"))]
        for ln in keep[-25:]:
            print("  " + ln[:200])
        if not keep:
            print("  (nimic relevant)")
    except OSError as e:
        print(f"  nu pot citi: {e}")


if __name__ == "__main__":
    main()
