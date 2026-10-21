"""
Responsive bar: the same config on a 2560 px PC and a 1920 px laptop at 125 % (1536 px for Qt).

Invisible widget, one per bar. Every second it measures the room each side has next to the
clock (the center stays exactly in the middle) and, when a side does not fit, hides that
side's least important widgets in the configured order; they come back as soon as there is
room again. Only widgets it hid itself are ever shown again, so widgets that hide on their own
(Bluetooth without a radio, the visualizer without music, modes) are left alone.
The bar also gets a tier class (tier-full / tier-normal / tier-dense / tier-min) chosen from
the room left beside the clock, which styles.css uses for tighter spacing and smaller text.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from core.events.service import EventService
from core.utils.qobject import is_valid_qobject
from core.validation.widgets.yasb.responsive import TIERS, ResponsiveConfig, TierThresholds
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb import mint_health as health
from core.widgets.yasb.bar_overflow import HIDDEN_EVENT
from core.widgets.yasb.mint_common import all_bar_widgets, find_named, make_invisible, refresh_tree, set_class_token


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


def tier_for(room: int, thresholds: TierThresholds, portrait: bool = False, portrait_max: str = "dense") -> str:
    """
    How tight the bar is, from the room left on one side of the clock.

    Read from the room, not from the screen's resolution: that way a large monitor scaled to
    150 % and a small laptop land on the same tier by themselves, with no per-screen setting
    written anywhere. A rotated screen has a laptop's problem whatever its pixel count, so it
    never goes above `portrait_max`.
    """
    if room >= thresholds.full:
        tier = "full"
    elif room >= thresholds.normal:
        tier = "normal"
    elif room >= thresholds.dense:
        tier = "dense"
    else:
        tier = "min"
    if portrait and TIERS.index(tier) > TIERS.index(portrait_max):
        tier = portrait_max
    return tier


def _really_hidden(widget) -> bool:
    try:
        return widget.isHidden()
    except RuntimeError:
        return False


def at_or_below(tier: str, limit: str) -> bool:
    """True when `tier` is as tight as `limit`, or tighter."""
    return TIERS.index(tier) <= TIERS.index(limit)


UNIT_HIDDEN = "_mint_unit_hidden"


def units_to_change(labels, show: bool) -> tuple[list, list]:
    """
    Which unit labels to hide / show, following the same rule as whole widgets: hide anything,
    but only ever show back what we hid ourselves.

    Without that rule this un-hid the *alt* labels too. A widget's alt label set is hidden by
    YASB until you click it, so the bar ended up reading "CPU 17% MHz 55°C": the percent from
    the normal label, and MHz from the alt one, side by side.
    """
    to_hide, to_show = [], []
    for label in labels:
        if not show:
            if not label.isHidden():
                to_hide.append(label)
        elif label.isHidden() and getattr(label, UNIT_HIDDEN, False):
            to_show.append(label)
    return to_hide, to_show


class ResponsiveWidget(BaseWidget):
    validation_schema = ResponsiveConfig

    def __init__(self, config: ResponsiveConfig):
        super().__init__(class_name="responsive")
        self.config = config
        make_invisible(self)
        self._tier: str | None = None
        self._watched: QWidget | None = None
        self._clock_column: QWidget | None = None
        self._overflow_widget: QWidget | None = None
        self._announced: str | None = None
        self._events = EventService()
        self._timer = QTimer(self)
        health.connect(self._timer, "responsive", self._tick)
        self.register_callback("show_health", self._show_health)
        self._timer.start(config.interval)
        QTimer.singleShot(600, self._tick)
        self._watch_screens()

    # ------------------------------------------------------------------ monitoare

    def _watch_screens(self) -> None:
        """
        Cand conectezi sau scoti un monitor, tot ce stiam despre bara devine vechi.

        Pana acum ramaneau referintele vechi la cadrul barei si la ceas, iar bara se stramba
        pana o reporneai. Acum le aruncam si masuram din nou.
        """
        app = QApplication.instance()
        if app is None:
            return
        for signal in (app.screenAdded, app.screenRemoved, app.primaryScreenChanged):
            signal.connect(self._screens_changed)

    def _screens_changed(self, *_args) -> None:
        self._watched = None
        self._tier = None
        self._clock_column = None
        QTimer.singleShot(0, self._tick)
        QTimer.singleShot(400, self._tick)  # Qt aseaza barele din nou: mai masuram o data dupa

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
        except Exception as exc:
            health.failed("responsive", exc, self._timer.stop)

    def _show_health(self) -> None:
        """Panoul „Starea barei”, deschis din lansator. Se aseaza sub mijlocul barei."""
        root = self.window()
        if root is None or root is self:
            return
        health.show_panel(self._frame(root))

    def _overflow(self, root: QWidget):
        """Sageata de la capatul barei, daca exista in bara asta."""
        if self._overflow_widget is not None and is_valid_qobject(self._overflow_widget):
            return self._overflow_widget
        from core.widgets.yasb.bar_overflow import BarOverflowWidget

        self._overflow_widget = next((w for w in all_bar_widgets(root) if isinstance(w, BarOverflowWidget)), None)
        return self._overflow_widget

    def _portrait(self, frame: QWidget) -> bool:
        screen = frame.screen()
        if screen is None:
            return False
        geometry = screen.geometry()
        return geometry.height() > geometry.width()

    def _apply_tier(self, frame: QWidget, room: int) -> None:
        tier = tier_for(room, self.config.tiers, self._portrait(frame), self.config.portrait_max_tier)
        if tier == self._tier:
            return
        self._tier = tier
        set_class_token(frame, f"tier-{tier}", True, prefix="tier-")
        # "compact" ramane pentru regulile scrise inainte de niveluri
        set_class_token(frame, "compact", tier != "full")
        self._apply_units(frame, tier)
        refresh_tree(frame)
        logging.info("responsive: side room %dpx -> tier %s", room, tier)

    def _apply_units(self, frame: QWidget, tier: str) -> None:
        """
        Unitatile (%, grade) se scriu doar cand e loc.

        Qt nu cunoaste "display: none", deci asta nu se poate face din stiluri. Etichetele de
        unitate nu sunt widget-uri de bara, deci nu trec prin arbitru: nimeni altcineva nu le
        atinge vizibilitatea.
        """
        show = not at_or_below(tier, self.config.hide_units_from)
        units = [lb for lb in frame.findChildren(QLabel) if "unit" in (lb.property("class") or "").split()]
        to_hide, to_show = units_to_change(units, show)
        for label in to_hide:
            setattr(label, UNIT_HIDDEN, True)
            label.setVisible(False)
        for label in to_show:
            setattr(label, UNIT_HIDDEN, False)
            label.setVisible(True)

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

        names = {n for n in self.config.hide_left + self.config.hide_right + list(self.config.flexible)}
        names |= {"clock"}
        found: dict[str, QWidget] = {}
        for w in find_named(names, root):
            found.setdefault(w.widget_name, w)  # type: ignore[attr-defined]

        clock = found.get("clock")
        center_col = self._column(clock, frame) if clock is not None else None
        center_w = self._hint(center_col) if center_col is not None else 0
        avail = (width - center_w) // 2 - self.config.margin
        self._apply_tier(frame, avail)
        overflow = self._overflow(root)

        for side in (self.config.hide_left, self.config.hide_right):
            widgets = [(n, found[n]) for n in side if n in found]
            if not widgets:
                continue
            column = self._column(widgets[0][1], frame)
            if column is None:
                continue
            need = self._hint(column)
            side_room = avail
            # The arrow at the end of the bar appears exactly when we hide something, and it
            # takes room itself — so it could cause the very hiding that made it appear, and
            # then oscillate as things come back. We keep its room reserved either way, and
            # leave it out of the measurement, so it never enters the arithmetic.
            if overflow is not None and self._column(overflow, frame) is column:
                reserve = self._hint(overflow)
                side_room -= reserve
                if not overflow.isHidden():
                    need = max(0, need - max(reserve, overflow.width()))
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
            to_hide, to_show = plan(need, side_room, order, self.config.hysteresis)
            for name in to_hide:
                visibility.request(found[name], visibility.SPACE, False)
            for name in to_show:
                visibility.request(found[name], visibility.SPACE, True)
            if to_hide or to_show:
                logging.info(
                    "responsive: bar %dpx, side room %dpx -> hidden %s, shown %s", width, side_room, to_hide, to_show
                )
        self._announce(found)

    def _announce(self, found: dict[str, QWidget]) -> None:
        """
        Spune cine a ramas pe dinafara, ca butonul de la capatul barei sa stie ce sa arate.

        Numai ce am ascuns noi din lipsa de loc: ce ascunde un mod, sau widget-ul insusi fiindca
        n-are ce arata, nu e "pe dinafara" — e ascuns cu rost.
        """
        # „ascuns de noi” nu e totuna cu „ascuns pe ecran”: unele widget-uri YASB se arata
        # singure dupa ce le-am ascuns, iar atunci lista de la capatul barei ar fi spus
        # „pe dinafara” despre ceva ce se vede. Cerem amandoua conditiile.
        hidden = sorted(
            name
            for name, w in found.items()
            if not visibility.wants(w, visibility.SPACE) and _really_hidden(w)
        )
        payload = ",".join(hidden)
        if payload == self._announced:
            return
        self._announced = payload
        self._events.emit_event(HIDDEN_EVENT, payload)
