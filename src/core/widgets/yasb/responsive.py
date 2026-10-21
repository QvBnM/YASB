"""
Responsive bar: the same config on a 2560 px PC and a 1920 px laptop at 125 % (1536 px for Qt).

Invisible widget, one per bar. Every second it measures the room each side has next to the
clock (the center stays exactly in the middle) and, when a side does not fit, hides that
side's least important widgets in the configured order; they come back as soon as there is
room again. Only widgets it hid itself are ever shown again, so widgets that hide on their own
(Bluetooth without a radio, the visualizer without music, modes) are left alone.
Below `compact_below` the bar gets the class "compact" for tighter spacing in styles.css.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QWidget

from core.validation.widgets.yasb.responsive import ResponsiveConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb.mint_common import find_named, make_invisible, refresh_tree, set_class_token


def plan(need: int, avail: int, order: list[tuple[str, int, bool]], hysteresis: int) -> tuple[list[str], list[str]]:
    """Which widgets to hide / show for one side.

    need  = width the side needs now (visible widgets only)
    avail = width the side may use
    order = (name, width, hidden_by_us) in hide order (first = least important)
    Returns (to_hide, to_show).
    """
    to_hide: list[str] = []
    to_show: list[str] = []
    if need > avail:
        for name, width, hidden in order:
            if need <= avail:
                break
            if not hidden and width > 0:
                to_hide.append(name)
                need -= width
        return to_hide, to_show
    # room to spare: bring back the most important hidden ones first (reverse order)
    for name, width, hidden in reversed(order):
        if not hidden:
            continue
        if need + width + hysteresis <= avail:
            to_show.append(name)
            need += width
        else:
            break  # keep the order: never show a less important one before a more important one
    return to_hide, to_show


class ResponsiveWidget(BaseWidget):
    validation_schema = ResponsiveConfig

    def __init__(self, config: ResponsiveConfig):
        super().__init__(class_name="responsive")
        self.config = config
        make_invisible(self)
        self._compact: bool | None = None
        self._watched: QWidget | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(config.interval)
        QTimer.singleShot(600, self._tick)

    # ------------------------------------------------------------------ helpers

    def _frame(self, root: QWidget) -> QWidget:
        for w in [root, *root.findChildren(QWidget)]:
            if "yasb-bar" in (w.property("class") or "").split():
                return w
        return root

    @staticmethod
    def _column(widget: QWidget, frame: QWidget) -> QWidget | None:
        """The bar column (left / center / right container) that holds this widget."""
        w = widget
        while w is not None and w.parentWidget() is not None and w.parentWidget() is not frame:
            w = w.parentWidget()
        return w if w is not None and w.parentWidget() is frame else None

    @staticmethod
    def _hint(w: QWidget) -> int:
        lay = w.layout()
        if lay is not None:
            lay.invalidate()
        return max(0, w.sizeHint().width())

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        if a1 is not None and a1.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._tick)
        return False

    # ------------------------------------------------------------------ main

    def _tick(self) -> None:
        try:
            self._apply()
        except RuntimeError:
            pass  # a widget was destroyed mid-measure: the next tick sees the new bar
        except Exception:
            logging.exception("responsive: evaluation failed")

    def _apply(self) -> None:
        root = self.window()
        if root is None or root is self:
            return
        frame = self._frame(root)
        if self._watched is not frame:
            frame.installEventFilter(self)
            self._watched = frame
        width = frame.width()
        if width <= 0:
            return

        compact = width < self.config.compact_below
        if compact != self._compact:
            self._compact = compact
            set_class_token(frame, "compact", compact)
            refresh_tree(frame)

        names = {n for n in self.config.hide_left + self.config.hide_right + list(self.config.flexible)}
        names |= {"clock"}
        found: dict[str, QWidget] = {}
        for w in find_named(names, root):
            found.setdefault(w.widget_name, w)  # type: ignore[attr-defined]

        clock = found.get("clock")
        center_col = self._column(clock, frame) if clock is not None else None
        center_w = self._hint(center_col) if center_col is not None else 0
        avail = (width - center_w) // 2 - self.config.margin

        for side in (self.config.hide_left, self.config.hide_right):
            widgets = [(n, found[n]) for n in side if n in found]
            if not widgets:
                continue
            column = self._column(widgets[0][1], frame)
            if column is None:
                continue
            need = self._hint(column)
            # flexible widgets (the window title) only count with their minimum
            for name, minimum in self.config.flexible.items():
                fw = found.get(name)
                if fw is not None and not fw.isHidden() and self._column(fw, frame) is column:
                    need += minimum - self._hint(fw)
            order = []
            for name, w in widgets:
                # a widget a mode hid, or that hid itself for want of data, is not ours to manage:
                # we only ever decide about room (see mint_visibility)
                if not (visibility.wants(w, visibility.MODE) and visibility.wants(w, visibility.SELF)):
                    continue
                hidden_by_us = not visibility.wants(w, visibility.SPACE)
                if w.isHidden() and not hidden_by_us:
                    continue  # hidden by YASB itself (media with hide_empty): not ours either
                order.append(
                    (name, self._hint(w) if hidden_by_us else max(1, w.width() or self._hint(w)), hidden_by_us)
                )
            to_hide, to_show = plan(need, avail, order, self.config.hysteresis)
            for name in to_hide:
                visibility.request(found[name], visibility.SPACE, False)
            for name in to_show:
                visibility.request(found[name], visibility.SPACE, True)
            if to_hide or to_show:
                logging.info(
                    "responsive: bar %dpx, side room %dpx -> hidden %s, shown %s", width, avail, to_hide, to_show
                )
