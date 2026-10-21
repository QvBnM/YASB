"""
Popup-urile YASB in romana si calendarul mai usor de citit, fara sa modifici codul YASB.

Widget invizibil. Asculta cand apare o fereastra (popup, meniu) si:
  - traduce textele fixe din YASB ("WiFi Networks", "Set Alarm", "Week 43"...),
    inclusiv cand widget-ul le rescrie mai tarziu;
  - in calendar: zilele din alte luni se sting, weekendul are alta nuanta,
    sarbatorile au culoarea din paleta si nume intregi, iar randul gol pentru
    sarbatoarea zilei arata cat mai e pana la urmatoarea zi libera.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QMenu, QWidget

from core.validation.widgets.yasb.ui_polish import UiPolishConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb.mint_common import PaletteWatcher, make_invisible, ro_day_month, ro_days

_PATCHED_CALENDAR = False
_CAL_COLORS: dict[str, str] = {}


# --------------------------------------------------------------------------- sarbatori


def merge_holidays(items: list[tuple[date, str]]) -> list[tuple[date, date, str]]:
    """Zilele consecutive cu acelasi nume devin un interval: 25-26 dec Craciunul."""
    out: list[tuple[date, date, str]] = []
    for d, name in sorted(items):
        if out and out[-1][2] == name and out[-1][1] + timedelta(days=1) == d:
            out[-1] = (out[-1][0], d, name)
        else:
            out.append((d, d, name))
    return out


def format_range(start: date, end: date) -> str:
    if start == end:
        return ro_day_month(start)
    if start.month == end.month:
        return f"{start.day}–{end.day} {ro_day_month(end).split(' ')[1]}"
    return f"{ro_day_month(start)} – {ro_day_month(end)}"


def upcoming_holidays(country_code: str, today: date) -> list[tuple[date, date, str]]:
    try:
        from core.widgets.yasb import clock
    except Exception:
        return []
    country = clock._supported_country(country_code)
    if not country:
        return []
    items: dict[date, str] = {}
    for year in (today.year, today.year + 1):
        items.update(clock._get_cached_country_holidays(country, year, None))
    return merge_holidays([(d, n) for d, n in items.items() if d >= today])


# --------------------------------------------------------------------------- calendar


def _patch_calendar() -> None:
    """Inlocuieste desenarea celulelor din calendarul YASB (o singura data, pentru toate barele)."""
    global _PATCHED_CALENDAR
    if _PATCHED_CALENDAR:
        return
    try:
        from PyQt6.QtCore import QDate

        from core.widgets.yasb import clock
    except Exception:
        logging.warning("ui_polish: calendarul YASB nu poate fi imbunatatit")
        return
    original = clock.CustomCalendar.paintCell

    def paint_cell(self, painter, rect, d):
        qdate = d if isinstance(d, QDate) else QDate(d.year, d.month, d.day)
        if painter is None or qdate < self.minimumDate() or qdate > self.maximumDate():
            return original(self, painter, rect, d)
        if _CAL_COLORS.get("holiday"):
            self.holiday_color = _CAL_COLORS["holiday"]
        selected = qdate == self.selectedDate()
        color = None
        if qdate.month() != self.monthShown():
            color = _CAL_COLORS.get("outside")
        elif not selected and qdate.dayOfWeek() in (6, 7) and qdate.toPyDate() not in getattr(self, "_holidays", set()):
            color = _CAL_COLORS.get("weekend")
        if color and not selected:
            painter.save()
            painter.setPen(QColor(color))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(qdate.day()))
            painter.restore()
            return None
        return original(self, painter, rect, d)

    clock.CustomCalendar.paintCell = paint_cell
    _PATCHED_CALENDAR = True


class UiPolishWidget(BaseWidget):
    validation_schema = UiPolishConfig

    def __init__(self, config: UiPolishConfig):
        super().__init__(class_name="ui-polish")
        self.config = config
        make_invisible(self)
        self._strings = {**config.strings, **config.extra_strings}
        self._patterns = [(re.compile(p.pattern), p.replacement) for p in config.patterns]
        self._palette = PaletteWatcher(self, self._on_palette)
        self._on_palette(self._palette.colors)
        if config.calendar.enabled:
            _patch_calendar()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _on_palette(self, colors: dict[str, str]) -> None:
        c = self.config.calendar
        _CAL_COLORS.update(
            weekend=colors.get(c.weekend_color, ""),
            outside=colors.get(c.outside_color, ""),
            holiday=colors.get(c.holiday_color, ""),
        )
        self._danger = colors.get(c.holiday_color, "#e78a8a")

    # ------------------------------------------------------------------ traducere

    def translate(self, text: str) -> str:
        if not text:
            return text
        if text in self._strings:
            return self._strings[text]
        for rx, repl in self._patterns:
            if rx.search(text):
                return rx.sub(repl, text)
        return text

    def _hook(self, w: QWidget) -> None:
        if getattr(w, "_mint_tr", False):
            return
        w._mint_tr = True  # type: ignore[attr-defined]
        original = w.setText  # type: ignore[attr-defined]

        def set_text(text):
            original(self.translate(text) if isinstance(text, str) else text)

        w.setText = set_text  # type: ignore[attr-defined]
        current = w.text()  # type: ignore[attr-defined]
        new = self.translate(current)
        if new != current:
            original(new)

    def _polish_tree(self, root: QWidget) -> None:
        try:
            widgets = [root, *root.findChildren(QWidget)][: self.config.max_label_scan]
            for w in widgets:
                if isinstance(w, (QLabel, QAbstractButton)):
                    self._hook(w)
                elif isinstance(w, QMenu):
                    for action in w.actions():
                        t = self.translate(action.text())
                        if t != action.text():
                            action.setText(t)
            if self.config.calendar.enabled:
                self._polish_calendar(root)
        except RuntimeError:
            pass  # fereastra s-a inchis intre timp

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        if a1 is not None and a1.type() == QEvent.Type.Show and isinstance(a0, QWidget):
            if a0.isWindow():
                QTimer.singleShot(0, lambda w=a0: self._polish_tree(w))
            elif isinstance(a0, (QLabel, QAbstractButton)) and not getattr(a0, "_mint_tr", False):
                self._hook(a0)
        return False

    # ------------------------------------------------------------------ calendar

    def _polish_calendar(self, root: QWidget) -> None:
        cfg = self.config.calendar
        labels = [lb for lb in root.findChildren(QLabel)]
        items = [lb for lb in labels if "upcoming-events-item" in (lb.property("class") or "").split()]
        holiday_label = next((lb for lb in labels if "holiday-label" in (lb.property("class") or "").split()), None)
        if not items and holiday_label is None:
            return
        today = date.today()
        upcoming = upcoming_holidays(cfg.country_code, today)

        if cfg.full_holiday_names and items:
            # randurile din popup si sarbatorile nu sunt mereu la fel de multe
            for lb, (start, end, name) in zip(items, upcoming, strict=False):
                lb.setWordWrap(True)
                lb.setTextFormat(Qt.TextFormat.RichText)
                QLabel.setText(lb, f"<span style='color:{self._danger}'>{format_range(start, end)}</span>&nbsp;&nbsp;{name}")
                lb.setToolTip("")

        if cfg.next_holiday and holiday_label is not None and not getattr(holiday_label, "_mint_next", False):
            holiday_label._mint_next = True  # type: ignore[attr-defined]
            nxt = next(((s, n) for s, _e, n in upcoming if s > today), None)
            fallback = ""
            if nxt:
                days = (nxt[0] - today).days
                when = ro_days(days) if days <= 1 else f"peste {ro_days(days)}"
                fallback = cfg.next_holiday_format.format(name=nxt[1], when=when)
            original = holiday_label.setText

            def set_text(text, _orig=original, _fb=fallback, _lb=holiday_label):
                if text:
                    set_class(_lb, False)
                    _orig(text)
                else:
                    set_class(_lb, bool(_fb))
                    _orig(_fb)

            holiday_label.setText = set_text  # type: ignore[method-assign]
            set_text(holiday_label.text())


def set_class(label: QLabel, upcoming: bool) -> None:
    tokens = [t for t in (label.property("class") or "").split() if t != "upcoming"]
    if upcoming:
        tokens.append("upcoming")
    new = " ".join(tokens)
    if new != label.property("class"):
        label.setProperty("class", new)
        label.style().unpolish(label)
        label.style().polish(label)
