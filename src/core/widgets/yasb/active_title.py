"""
Active window title that uses all the free room up to the clock, without touching it.

Same as yasb.active_window.ActiveWindowWidget, but instead of a fixed number of characters
the title is cut ("…") at the width that is left between it and the clock in the bar's
center. Re-measured every second, so it adapts when the media player appears or disappears.
"""

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import QLabel, QWidget

from core.utils.qobject import is_valid_qobject
from core.validation.widgets.yasb.active_title import ActiveTitleConfig
from core.widgets.yasb.active_window import ActiveWindowWidget


class ActiveTitleWidget(ActiveWindowWidget):
    validation_schema = ActiveTitleConfig

    def __init__(self, config: ActiveTitleConfig):
        super().__init__(config)
        self._full_title = ""
        self._clock: QWidget | None = None
        label = self._window_title_text
        self._full_title = label.text()
        # YASB sets the title through label.setText(...) from Python: route it through the fitter
        label.setText = self._set_full_title  # type: ignore[method-assign]
        self._fit_timer = QTimer(self)
        self._fit_timer.setInterval(1000)
        self._fit_timer.timeout.connect(self._fit)
        self._fit_timer.start()

    def _set_full_title(self, text: str) -> None:
        self._full_title = text or ""
        self._fit()

    def _find_clock(self) -> QWidget | None:
        if self._clock is not None and is_valid_qobject(self._clock) and self._clock.isVisible():
            return self._clock
        self._clock = None
        bar = self.window()
        if bar is None:
            return None
        for w in bar.findChildren(QWidget):
            if "clock-widget" in str(w.property("class") or "").split() and w.isVisible():
                self._clock = w
                break
        return self._clock

    def _available_width(self, label: QLabel) -> int | None:
        if not label.isVisible():
            return None
        bar = self.window()
        if bar is None:
            return None
        # measure from the bar's real center, not from where the clock is drawn right now:
        # if the left side ever grew past the middle it would push the clock, and the title
        # would then chase it. The clock keeps its width, so this limit never moves.
        center = bar.mapToGlobal(QPoint(bar.width() // 2, 0)).x()
        clock = self._find_clock()
        limit = center - (clock.width() // 2 if clock is not None else 0)
        left = label.mapToGlobal(QPoint(0, 0)).x()
        # what sits right of the label inside this widget (container padding, margins)
        right_extra = self.mapToGlobal(QPoint(self.width(), 0)).x() - label.mapToGlobal(QPoint(label.width(), 0)).x()
        return max(self.config.min_width, limit - left - max(right_extra, 0) - self.config.gap)

    def _fit(self) -> None:
        label = self._window_title_text
        if not is_valid_qobject(label):
            return
        width = self._available_width(label)
        text = self._full_title
        if width is not None and text:
            text = label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)
        if QLabel.text(label) != text:
            QLabel.setText(label, text)
