"""
Ping catre un server (implicit 1.1.1.1), cu API-ul ICMP din Windows (iphlpapi).

Nu porneste ping.exe si nu deschide ferestre; masurarea ruleaza pe un fir separat,
deci bara nu se blocheaza cand reteaua nu raspunde.
"""

from __future__ import annotations

import ctypes
import logging
import socket
import threading
from ctypes import wintypes

from PyQt6.QtCore import QTimer, pyqtSignal

from core.validation.widgets.yasb.latency import LatencyConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb.mint_common import fill_labels, set_class_token, toggle_alt


class _IpOptionInformation(ctypes.Structure):
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    ]


class _IcmpEchoReply(ctypes.Structure):
    _fields_ = [
        ("Address", wintypes.ULONG),
        ("Status", wintypes.ULONG),
        ("RoundTripTime", wintypes.ULONG),
        ("DataSize", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("Data", ctypes.c_void_p),
        ("Options", _IpOptionInformation),
    ]


def icmp_ping(host: str, timeout_ms: int) -> int | None:
    """Timpul dus-intors in ms, sau None daca nu a raspuns."""
    try:
        ip = socket.gethostbyname(host)
        addr = int.from_bytes(socket.inet_aton(ip), "little")  # IPAddr = ordinea din retea, citita ca ULONG
        iphlpapi = ctypes.windll.iphlpapi
        iphlpapi.IcmpCreateFile.restype = wintypes.HANDLE
        iphlpapi.IcmpSendEcho.argtypes = [
            wintypes.HANDLE,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.WORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        iphlpapi.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        handle = iphlpapi.IcmpCreateFile()
        if not handle or handle == wintypes.HANDLE(-1).value:
            return None
        try:
            payload = b"mintbar!" * 4
            size = ctypes.sizeof(_IcmpEchoReply) + len(payload) + 8
            reply = ctypes.create_string_buffer(size)
            n = iphlpapi.IcmpSendEcho(handle, addr, payload, len(payload), None, reply, size, timeout_ms)
            if n == 0:
                return None
            echo = _IcmpEchoReply.from_buffer(reply)
            return int(echo.RoundTripTime) if echo.Status == 0 else None
        finally:
            iphlpapi.IcmpCloseHandle(handle)
    except Exception:
        logging.debug("latency: ping esuat", exc_info=True)
        return None


class LatencyWidget(BaseWidget):
    validation_schema = LatencyConfig
    _result = pyqtSignal(object)

    def __init__(self, config: LatencyConfig):
        super().__init__(class_name=f"latency-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._busy = False
        self._last: int | None = None
        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        self.register_callback("toggle_label", self._toggle)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        self._result.connect(self._on_result)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._measure)
        self._timer.start(config.update_interval)
        self._measure()

    def _toggle(self) -> None:
        toggle_alt(self)
        self._render()

    def _measure(self) -> None:
        if self._busy or not self.isVisible() and self._last is not None:
            return
        self._busy = True

        def work():
            ms = icmp_ping(self.config.host, self.config.timeout)
            try:
                self._result.emit(ms)
            except RuntimeError:
                pass  # widget-ul a fost distrus intre timp

        threading.Thread(target=work, name="mint-latency", daemon=True).start()

    def _on_result(self, ms: int | None) -> None:
        self._busy = False
        self._last = ms
        self._render()

    def _render(self) -> None:
        ms = self._last
        values = {"ms": "--" if ms is None else ms, "host": self.config.host}
        fill_labels(self, values)
        for lb in self._widgets + self._widgets_alt:
            set_class_token(lb, "timeout", ms is None)
