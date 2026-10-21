"""
Linia de jos a barei arata progresul: melodia, sesiunea de focus (pomodoro), download-urile.

Widget invizibil. Deseneaza o linie de cativa pixeli peste bordura de jos a barei,
lata cat procentul sursei active. Culoarea spune sursa si vine din palette.css,
deci se schimba odata cu wallpaper-ul.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QWidget

from core.validation.widgets.yasb.progress_line import ProgressLineConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb.mint_common import PaletteWatcher, make_invisible

TICK_MS = 250


def torrents_progress(torrents: list[dict]) -> float | None:
    """Progresul total al torrentelor in descarcare, ponderat cu marimea."""
    total = sum(max(0, int(t.get("size") or 0)) for t in torrents)
    if total <= 0:
        return None
    done = sum(max(0, int(t.get("size") or 0)) * float(t.get("progress") or 0.0) for t in torrents)
    return max(0.0, min(1.0, done / total))


class ProgressLineWidget(BaseWidget):
    validation_schema = ProgressLineConfig
    _qbt_result = pyqtSignal(object)

    def __init__(self, config: ProgressLineConfig):
        super().__init__(class_name="progress-line")
        self.config = config
        make_invisible(self)

        self._host: QWidget | None = None
        self._line: QFrame | None = None
        self._started: dict[str, float] = {}
        self._current_color = ""
        self._media = None
        self._qbt_value: float | None = None
        self._qbt_busy = False
        self._qbt_at = 0.0
        self._qbt_result.connect(self._on_qbt)
        self._palette = PaletteWatcher(self, lambda _c: self._force_color())

        if "media" in config.sources:
            try:
                from core.widgets.services.media.media import WindowsMedia

                self._media = WindowsMedia()
            except Exception:
                logging.warning("progress_line: serviciul media nu e disponibil")

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(TICK_MS)

    # ------------------------------------------------------------------ surse

    def _pomodoro(self) -> float | None:
        try:
            from core.widgets.yasb.pomodoro import PomodoroWidget
        except Exception:
            return None
        s = PomodoroWidget._shared_state
        if not (s.get("is_running") or s.get("is_paused")) or not PomodoroWidget._instances:
            return None
        try:
            cfg = PomodoroWidget._instances[0].config
        except RuntimeError:
            return None
        if s.get("is_break"):
            total = (cfg.long_break_duration if s.get("is_long_break") else cfg.break_duration) * 60
        else:
            total = cfg.work_duration * 60
        remaining = s.get("remaining_time") or 0
        return max(0.0, min(1.0, 1 - remaining / total)) if total else None

    def _media_progress(self) -> float | None:
        if self._media is None:
            return None
        try:
            cs = self._media.current_session
        except Exception:
            return None
        if cs is None or cs.duration <= 0 or not (cs.is_playing or self.config.media_paused):
            return None
        return max(0.0, min(1.0, cs.current_pos / cs.duration))

    def _qbittorrent(self) -> float | None:
        q = self.config.qbittorrent
        if not q.enabled:
            return None
        now = time.monotonic()
        if not self._qbt_busy and now - self._qbt_at > q.interval / 1000:
            self._qbt_busy = True
            self._qbt_at = now
            url = q.url.rstrip("/") + "/api/v2/torrents/info?filter=downloading"

            def work():
                try:
                    with urllib.request.urlopen(url, timeout=2) as r:
                        value = torrents_progress(json.loads(r.read().decode("utf-8")))
                except Exception:
                    value = None
                try:
                    self._qbt_result.emit(value)
                except RuntimeError:
                    pass

            threading.Thread(target=work, name="mint-qbt", daemon=True).start()
        return self._qbt_value

    def _on_qbt(self, value: float | None) -> None:
        self._qbt_busy = False
        self._qbt_value = value

    # ------------------------------------------------------------------ desen

    def _ensure_line(self) -> bool:
        host = self.window()
        if host is None or host is self:
            return False
        if self._host is host and self._line is not None:
            return True
        self._host = host
        line = QFrame(host)
        line.setObjectName("mintProgressLine")
        line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        line.hide()
        self._line = line
        host.installEventFilter(self)
        self._force_color()
        return True

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        if a0 is self._host and a1 is not None and a1.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._tick)
        return False

    def _force_color(self) -> None:
        self._current_color = ""

    def _set_color(self, source: str) -> None:
        name = self.config.colors.get(source, "accent")
        color = self._palette.colors.get(name, self._palette.colors["accent"])
        if color != self._current_color and self._line is not None:
            self._current_color = color
            self._line.setStyleSheet(f"#mintProgressLine {{ background-color: {color}; border: none; }}")

    def _tick(self) -> None:
        if not self._ensure_line():
            return
        values: dict[str, float] = {}
        for src in self.config.sources:
            try:
                v = {"pomodoro": self._pomodoro, "media": self._media_progress, "qbittorrent": self._qbittorrent}[src]()
            except Exception:
                logging.debug("progress_line: sursa %s a esuat", src, exc_info=True)
                v = None
            if v is None:
                self._started.pop(src, None)
            else:
                self._started.setdefault(src, time.monotonic())
                values[src] = v

        line, host = self._line, self._host
        assert line is not None and host is not None
        if not values:
            line.hide()
            return
        if self.config.pick == "latest":
            src = max(values, key=lambda s: self._started.get(s, 0.0))
        else:
            src = next(s for s in self.config.sources if s in values)
        self._set_color(src)
        h = self.config.height
        y = host.height() - h if self.config.position == "bottom" else 0
        width = round(host.width() * values[src])
        line.setGeometry(0, y, max(0, width), h)
        line.setVisible(width > 0)
        line.raise_()
