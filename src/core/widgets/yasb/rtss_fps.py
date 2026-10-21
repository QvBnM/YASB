"""
FPS-ul jocului din RivaTuner Statistics Server (vine cu MSI Afterburner).

Citeste memoria partajata "RTSSSharedMemoryV2", la fel cum hwinfo_sensor citeste HWiNFO:
nimic de instalat in plus, doar RTSS pornit. Se ascunde singur cand RTSS nu ruleaza
sau jocul activ nu are overlay.
"""

from __future__ import annotations

import ctypes
import logging
import struct
from dataclasses import dataclass

from PyQt6.QtCore import QTimer

from core.validation.widgets.yasb.rtss_fps import RtssFpsConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb.mint_common import fill_labels, foreground, toggle_alt

RTSS_SIGNATURE = 0x52545353  # "RTSS"
MAPPING_NAME = "RTSSSharedMemoryV2"
HEADER = struct.Struct("<8I")  # signature, version, appEntrySize, appArrOffset, appArrSize, osdEntrySize, osdArrOffset, osdArrSize
APP_PID = struct.Struct("<I")
APP_NAME_LEN = 260
APP_TAIL = struct.Struct("<5I")  # flags, time0, time1, frames, frameTime(us)


@dataclass
class RtssApp:
    pid: int
    name: str
    fps: float
    frametime_ms: float
    time1: int


def parse_rtss(buf: bytes) -> list[RtssApp]:
    """Aplicatiile cu overlay activ dintr-o copie a memoriei partajate RTSS."""
    if len(buf) < HEADER.size:
        return []
    sig, _ver, entry_size, arr_off, arr_size, *_ = HEADER.unpack_from(buf, 0)
    if sig != RTSS_SIGNATURE or entry_size < 4 + APP_NAME_LEN + APP_TAIL.size:
        return []
    apps: list[RtssApp] = []
    for i in range(arr_size):
        base = arr_off + i * entry_size
        if base + entry_size > len(buf):
            break
        (pid,) = APP_PID.unpack_from(buf, base)
        if not pid:
            continue
        raw_name = buf[base + 4 : base + 4 + APP_NAME_LEN].split(b"\0", 1)[0]
        _flags, t0, t1, frames, frame_time = APP_TAIL.unpack_from(buf, base + 4 + APP_NAME_LEN)
        fps = 1000.0 * frames / (t1 - t0) if t1 > t0 else 0.0
        name = raw_name.decode("mbcs" if hasattr(ctypes, "windll") else "latin-1", "replace").rsplit("\\", 1)[-1]
        apps.append(RtssApp(pid, name, fps, frame_time / 1000.0, t1))
    return apps


class _RtssReader:
    FILE_MAP_READ = 0x0004

    def __init__(self):
        self._handle = None
        self._view = None

    def _open(self) -> bool:
        if self._view:
            return True
        k32 = ctypes.windll.kernel32
        k32.OpenFileMappingW.restype = ctypes.c_void_p
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        handle = k32.OpenFileMappingW(self.FILE_MAP_READ, False, MAPPING_NAME)
        if not handle:
            return False  # RTSS nu ruleaza; nu cream noi maparea, ca sa nu o stricam
        view = k32.MapViewOfFile(handle, self.FILE_MAP_READ, 0, 0, 0)
        if not view:
            k32.CloseHandle(ctypes.c_void_p(handle))
            return False
        self._handle, self._view = handle, view
        return True

    def close(self) -> None:
        if not self._view:
            return
        k32 = ctypes.windll.kernel32
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.UnmapViewOfFile(ctypes.c_void_p(self._view))
        k32.CloseHandle(ctypes.c_void_p(self._handle))
        self._handle = self._view = None

    def read(self) -> list[RtssApp]:
        try:
            if not self._open():
                return []
            header = ctypes.string_at(self._view, HEADER.size)
            sig, _v, entry_size, arr_off, arr_size, *_ = HEADER.unpack(header)
            if sig != RTSS_SIGNATURE:
                self.close()  # 0xDEAD = RTSS s-a inchis; redeschidem la urmatorul tick
                return []
            size = arr_off + entry_size * arr_size
            if size <= 0 or size > 64 * 1024 * 1024:
                return []
            return parse_rtss(ctypes.string_at(self._view, size))
        except Exception:
            logging.debug("rtss: citire esuata", exc_info=True)
            self.close()
            return []


class RtssFpsWidget(BaseWidget):
    validation_schema = RtssFpsConfig

    def __init__(self, config: RtssFpsConfig):
        super().__init__(class_name=f"rtss-fps-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._reader = _RtssReader()
        self._self_hidden = False  # ne aratam singuri doar daca ne-am ascuns singuri (vezi context_mode)
        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        self.register_callback("toggle_label", self._toggle)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(config.update_interval)
        reader = self._reader
        self.destroyed.connect(lambda *_: reader.close())
        self._update()

    def _toggle(self) -> None:
        toggle_alt(self)
        self._update()

    def _pick(self, apps: list[RtssApp]) -> RtssApp | None:
        live = [a for a in apps if a.fps > 0]
        if not live:
            return None
        if self.config.foreground_only:
            pid = foreground().pid
            return next((a for a in live if a.pid == pid), None)
        return max(live, key=lambda a: a.time1)

    def _update(self) -> None:
        app = self._pick(self._reader.read())
        if app is None:
            if self.config.hide_if_unavailable and not self.isHidden():
                self._self_hidden = True
                self.setVisible(False)
            fill_labels(self, {"fps": "--", "frametime": 0.0, "app": ""})
            return
        if self._self_hidden:
            self._self_hidden = False
            self.setVisible(True)
        fill_labels(self, {"fps": round(app.fps), "frametime": app.frametime_ms, "app": app.name})
