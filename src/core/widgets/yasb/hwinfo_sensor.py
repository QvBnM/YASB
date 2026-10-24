"""
HWiNFO sensor widget: shows one HWiNFO64 reading (by default the CPU temperature).

Reads HWiNFO's shared memory ("Global\\HWiNFO_SENS_SM2") directly, so nothing else
has to run. In HWiNFO: Settings -> "Shared Memory Support" must be enabled and the
Sensors window must be open (it can be minimized to the tray).
Note: the free HWiNFO version turns shared memory off after 12 hours.
"""

import ctypes
import logging
import re
import struct
import subprocess
import time
from dataclasses import dataclass

from PyQt6.QtCore import QTimer

from core.utils.tooltip import set_tooltip
from core.validation.widgets.yasb.hwinfo_sensor import HwinfoSensorConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb import mint_health as health
from core.widgets.yasb.mint_common import ttl_cache

SHARED_MEMORY_NAME = "Global\\HWiNFO_SENS_SM2"
SIGNATURE = 0x53695748  # "HWiS"
HEADER = struct.Struct("<IIIqIIIIII")  # packed, 44 bytes
READING_TYPES = {
    "none": 0,
    "temperature": 1,
    "voltage": 2,
    "fan": 3,
    "current": 4,
    "power": 5,
    "clock": 6,
    "usage": 7,
    "other": 8,
}


@dataclass
class Reading:
    type: int
    sensor_index: int
    reading_id: int
    label: str
    unit: str
    value: float
    min: float
    max: float
    avg: float
    sensor: str


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1", errors="replace").strip()


def parse_shared_memory(buf: bytes) -> list[Reading]:
    """Parse a HWiNFO_SENS_SM2 snapshot (layout from the HWiNFO shared memory SDK)."""
    if len(buf) < HEADER.size:
        return []
    sig, _ver, _rev, _poll, s_off, s_size, s_num, r_off, r_size, r_num = HEADER.unpack_from(buf, 0)
    if sig != SIGNATURE:
        return []
    sensors = []
    for i in range(s_num):
        base = s_off + i * s_size
        if base + 264 > len(buf):
            break
        user = _cstr(buf[base + 136 : base + 264])
        orig = _cstr(buf[base + 8 : base + 136])
        sensors.append(user or orig)
    readings: list[Reading] = []
    for i in range(r_num):
        base = r_off + i * r_size
        if base + 316 > len(buf):
            break
        rtype, s_idx, r_id = struct.unpack_from("<III", buf, base)
        label_orig = _cstr(buf[base + 12 : base + 140])
        label_user = _cstr(buf[base + 140 : base + 268])
        unit = _cstr(buf[base + 268 : base + 284])
        value, vmin, vmax, vavg = struct.unpack_from("<dddd", buf, base + 284)
        readings.append(
            Reading(
                rtype,
                s_idx,
                r_id,
                label_user or label_orig,
                unit,
                value,
                vmin,
                vmax,
                vavg,
                sensors[s_idx] if s_idx < len(sensors) else "",
            )
        )
    return readings


def read_shared_memory() -> bytes | None:
    """Snapshot of HWiNFO's shared memory, or None when HWiNFO isn't sharing."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return None  # not Windows
    FILE_MAP_READ = 0x0004
    kernel32.OpenFileMappingW.restype = ctypes.c_void_p
    kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.MapViewOfFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_size_t,
    ]
    kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenFileMappingW(FILE_MAP_READ, 0, SHARED_MEMORY_NAME)
    if not handle:
        return None
    view = None
    try:
        view = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
        if not view:
            return None
        header = ctypes.string_at(view, HEADER.size)
        sig, _v, _r, _p, s_off, s_size, s_num, r_off, r_size, r_num = HEADER.unpack(header)
        if sig != SIGNATURE:
            return None
        total = max(s_off + s_size * s_num, r_off + r_size * r_num)
        return ctypes.string_at(view, total)
    finally:
        if view:
            kernel32.UnmapViewOfFile(view)
        kernel32.CloseHandle(handle)


def pick_reading(readings: list[Reading], match: list[str], rtype: int | None, sensor_match: str) -> Reading | None:
    pool = [r for r in readings if (rtype is None or r.type == rtype)]
    if sensor_match:
        pool = [r for r in pool if sensor_match.lower() in r.sensor.lower()]
    for pattern in match:
        p = pattern.lower()
        exact = [r for r in pool if r.label.lower() == p]
        if exact:
            return exact[0]
        partial = [r for r in pool if p in r.label.lower()]
        if partial:
            return partial[0]
    return None


@ttl_cache(400)
def readings() -> list[Reading]:
    """Senzorii HWiNFO, o singura citire pentru toate barele.

    Cu screens: ["*"] exista un cpu_temp in fiecare bara, si fiecare deschidea harta de memorie
    partajata, o copia intreaga si o parsa — pentru acelasi raspuns, la fiecare update_interval.
    400 ms e sub cel mai mic interval permis (500), deci nimeni nu vede o valoare mai veche decat
    propria lui masuratoare; barele care bat aproape in acelasi timp iau raspunsul gata facut.

    Lista intoarsa e aceeasi pentru toti, deci nu se umbla in ea: pick_reading doar filtreaza.
    """
    buf = read_shared_memory()
    return parse_shared_memory(buf) if buf else []


class HwinfoSensorWidget(BaseWidget):
    validation_schema = HwinfoSensorConfig

    def __init__(self, config: HwinfoSensorConfig):
        super().__init__(class_name=f"hwinfo-sensor-widget {config.class_name}")
        self.config = config
        self._show_alt = False
        self._key: tuple[int, int] | None = None  # (sensor index, reading id) once found
        self._missing_since: float | None = None
        self._last_restart = 0.0
        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)
        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("update_label", self._update)
        self.callback_left = self.config.callbacks.on_left
        self.callback_right = self.config.callbacks.on_right
        self.callback_middle = self.config.callbacks.on_middle

        self._timer = QTimer(self)
        self._timer.setInterval(self.config.update_interval)
        health.connect(self._timer, "cpu_temp", self._update)
        self._timer.start()
        self._update()

    def _toggle_label(self) -> None:
        self._show_alt = not self._show_alt
        for w in self._widgets:
            w.setVisible(not self._show_alt)
        for w in self._widgets_alt:
            w.setVisible(self._show_alt)
        self._update()

    def _find(self) -> Reading | None:
        found = readings()
        if not found:
            return None
        if self._key is not None:
            for r in found:
                if (r.sensor_index, r.reading_id) == self._key:
                    return r
            self._key = None  # HWiNFO restarted / sensors changed: search again
        rtype = None if self.config.reading_type == "any" else READING_TYPES[self.config.reading_type]
        r = pick_reading(found, self.config.match, rtype, self.config.sensor_match)
        if r is not None:
            self._key = (r.sensor_index, r.reading_id)
            logging.info("HWiNFO sensor: using '%s' from '%s'", r.label, r.sensor)
        return r

    def _watch_hwinfo(self, have_data: bool) -> None:
        """Restart HWiNFO through its scheduled task when the data has been gone for a while."""
        now = time.monotonic()
        if have_data:
            self._missing_since = None
            return
        if self._missing_since is None:
            self._missing_since = now
            return
        task = self.config.restart_task
        if not task or now - self._missing_since < self.config.restart_after:
            return
        if self._last_restart and now - self._last_restart < self.config.restart_every:
            return
        self._last_restart = now
        try:
            subprocess.Popen(
                ["schtasks", "/run", "/tn", task],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            logging.info(
                "HWiNFO sensor: no data for %ds, restarting HWiNFO (task '%s')", now - self._missing_since, task
            )
        except Exception as e:
            logging.warning("HWiNFO sensor: cannot run task '%s': %s", task, e)

    def _update(self) -> None:
        try:
            r = self._find()
        except Exception as e:
            logging.debug("HWiNFO read failed: %s", e)
            r = None
        widgets = self._widgets_alt if self._show_alt else self._widgets
        self._watch_hwinfo(r is not None)
        if r is None:
            if self.config.hide_if_unavailable:
                # nu chemam hide(): spunem doar ca n-avem ce arata, iar arbitrul hotaraste.
                # Asa nu mai reaparem peste un mod care tocmai ne-a ascuns.
                visibility.request(self, visibility.SELF, False)
            else:
                for w in widgets:
                    w.setText(self.config.unavailable_label)
            if self.config.tooltip:
                set_tooltip(self, "HWiNFO: pornește Sensors cu Shared Memory Support activat")
            return
        visibility.request(self, visibility.SELF, True)
        fmt = f"{{:>{self.config.value_width}.{self.config.precision}f}}"
        values = {
            "{value}": fmt.format(r.value),
            "{min}": fmt.format(r.min),
            "{max}": fmt.format(r.max),
            "{avg}": fmt.format(r.avg),
            "{unit}": r.unit,
            "{label}": r.label,
            "{sensor}": r.sensor,
        }
        template = self.config.label_alt if self._show_alt else self.config.label
        parts = [p for p in re.split(r"(<span.*?>.*?</span>)", template) if p and p.strip()]
        for i, part in enumerate(parts):
            if i >= len(widgets):
                break
            text = re.sub(r"<span.*?>|</span>", "", part).strip() if "<span" in part else part.strip()
            for k, v in values.items():
                text = text.replace(k, v)  # padding added by value_width stays in place
            widgets[i].setText(text)
        if self.config.tooltip:
            set_tooltip(
                self,
                f"{r.sensor}\n{r.label}: {values['{value}']}{r.unit}\n"
                f"min {values['{min}']} · max {values['{max}']} · medie {values['{avg}']}",
            )
