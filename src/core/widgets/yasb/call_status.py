"""
"În apel 12:04" cat timp o aplicatie inregistreaza de la microfon (Discord, Teams, Zoom...).

Foloseste aceeasi evidenta ca iconita de microfon din tray-ul Windows, deci nu are nevoie
de integrare cu fiecare aplicatie. Se ascunde singur cand nu esti in apel.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QTimer

from core.validation.widgets.yasb.call_status import CallStatusConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb.mint_common import fill_labels, mic_users, toggle_alt


def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class CallStatusWidget(BaseWidget):
    validation_schema = CallStatusConfig

    def __init__(self, config: CallStatusConfig):
        super().__init__(class_name=f"call-status-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._started: float | None = None
        self._last_seen = 0.0
        self._app = ""
        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        self.register_callback("toggle_label", self._toggle)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        visibility.request(self, visibility.SELF, False)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(config.update_interval)

    def _toggle(self) -> None:
        toggle_alt(self)
        self._update()

    def _update(self) -> None:
        now = time.monotonic()
        users = mic_users(self.config.ignore)
        if users:
            self._last_seen = now
            self._app = users[0]
            if self._started is None:
                self._started = now
        elif self._started is not None and now - self._last_seen > self.config.grace:
            self._started = None

        if self._started is None:
            visibility.request(self, visibility.SELF, False)
            return
        visibility.request(self, visibility.SELF, True)
        fill_labels(self, {"elapsed": format_elapsed(now - self._started), "app": self._app})
