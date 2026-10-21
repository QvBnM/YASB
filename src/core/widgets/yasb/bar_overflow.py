"""
Butonul de la capatul barei: ce nu mai incape, la un click distanta.

Pe un ecran foarte stramt raman ora si capsula de stari; procesorul, placa video, memoria,
traficul si vremea nu mai incap. Sageata de la capat deschide o lista scurta cu exact ce a
ascuns bara, cu valorile lor de acum.

De ce lista arata valorile si nu deschide popup-urile widget-urilor:
    popup-urile YASB se aseaza fata de widget-ul lor parinte (PopupWidget.setPosition citeste
    parent.mapToGlobal si parent.width). Un widget ascuns nu mai e in asezare, deci pozitia lui
    e veche sau zero, iar popup-ul ar aparea unde nimeri. Textul il citim din etichetele pe care
    widget-ul le tine oricum la zi, deci nu mutam nimic si nu depindem de nicio geometrie.

Widget-ul se arata singur doar cand bara chiar a ascuns ceva, si se ascunde la loc cand e
iar loc. Nu cheama setVisible: trece prin arbitru, ca toate celelalte (mint_visibility).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from core.events.service import EventService
from core.utils.qobject import is_valid_qobject
from core.utils.utilities import PopupWidget
from core.validation.widgets.yasb.bar_overflow import BarOverflowConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb.mint_common import fill_labels, find_named

HIDDEN_EVENT = "MintBarHidden"


def widget_text(widget) -> str:
    """Ce scrie widget-ul acum, citit din etichetele lui."""
    parts = []
    try:
        labels = getattr(widget, "_widgets", None) or []
    except RuntimeError:
        return ""  # widget-ul a fost distrus intre timp
    for label in labels:
        try:
            if label.isHidden():
                continue  # la latimi mici unitatile sunt ascunse: nu le punem inapoi
            text = (label.text() or "").strip()
        except (RuntimeError, AttributeError):
            return ""
        if text:
            parts.append(text)
    return " ".join(parts)


def rows_for(hidden: list[str], entries: list, known: dict[str, object]) -> list[tuple[str, str, str]]:
    """
    (titlu, iconita, nume) pentru fiecare widget ascuns care merita aratat.

    Cu `entries` scrise in config pastram ordinea si numele lor, dar sarim peste ce nu e
    ascuns acum. Fara `entries`, aratam tot ce a ascuns bara.
    """
    if entries:
        return [(e.title or e.widget, e.icon, e.widget) for e in entries if e.widget in hidden]
    return [(name, "", name) for name in hidden if name in known]


class _Row(QFrame):
    def __init__(self, title: str, icon: str, value: str):
        super().__init__()
        self.setProperty("class", "row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if icon:
            glyph = QLabel(icon)
            glyph.setProperty("class", "row-icon")
            layout.addWidget(glyph)
        name = QLabel(title)
        name.setProperty("class", "row-title")
        self.value = QLabel(value)
        self.value.setProperty("class", "row-value")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(name)
        layout.addStretch()
        layout.addWidget(self.value)


class BarOverflowWidget(BaseWidget):
    validation_schema = BarOverflowConfig
    _hidden_signal = pyqtSignal(str)

    def __init__(self, config: BarOverflowConfig):
        super().__init__(class_name=f"bar-overflow-widget {config.class_name}")
        self.config = config
        self._hidden: list[str] = []
        self._menu: PopupWidget | None = None
        self._rows: list[tuple[_Row, str]] = []

        self._init_container()
        self.build_widget_label(config.label)
        self.register_callback("toggle_menu", self._toggle_menu)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        fill_labels(self, {"icon": config.icon})

        # cat timp lista e deschisa, cifrele din ea raman vii
        self._refresh = QTimer(self)
        self._refresh.setInterval(config.refresh_interval)
        self._refresh.timeout.connect(self._refresh_values)

        self._events = EventService()
        self._hidden_signal.connect(self._on_hidden)
        self._events.register_event(HIDDEN_EVENT, self._hidden_signal)
        events, signal = self._events, self._hidden_signal  # fara referinte la self dupa distrugere
        self.destroyed.connect(lambda *_: events.unregister_event(HIDDEN_EVENT, signal))

        visibility.request(self, visibility.SELF, False)  # pana aflam ca s-a ascuns ceva

    # ------------------------------------------------------------------ ce s-a ascuns

    def _on_hidden(self, names: str) -> None:
        self._hidden = [n for n in names.split(",") if n]
        visibility.request(self, visibility.SELF, bool(self._rows_now()))
        if self._menu is not None and is_valid_qobject(self._menu) and self._menu.isVisible():
            self._fill_menu()

    def _known(self) -> dict[str, object]:
        root = self.window()
        return {getattr(w, "widget_name", ""): w for w in find_named(self._hidden, root)} if root else {}

    def _rows_now(self) -> list[tuple[str, str, str]]:
        return rows_for(self._hidden, self.config.entries, self._known())

    # ------------------------------------------------------------------ lista

    def _toggle_menu(self) -> None:
        if self._menu is not None and is_valid_qobject(self._menu) and self._menu.isVisible():
            self._menu.hide()
            self._refresh.stop()
            return
        self._show_menu()

    def _show_menu(self) -> None:
        m = self.config.menu
        if self._menu is not None and is_valid_qobject(self._menu):
            self._menu.deleteLater()  # altfel fiecare deschidere lasa in urma fereastra dinainte
        self._menu = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        self._menu.setProperty("class", "bar-overflow-menu")
        layout = QVBoxLayout(self._menu)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._body = QFrame()
        self._body.setProperty("class", "body")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setSpacing(0)
        layout.addWidget(self._body)

        self._fill_menu()
        self._menu.adjustSize()
        self._menu.setPosition(
            alignment=m.alignment, direction=m.direction, offset_left=m.offset_left, offset_top=m.offset_top
        )
        self._menu.show()
        self._refresh.start()

    def _fill_menu(self) -> None:
        if self._menu is None or not is_valid_qobject(self._menu):
            return
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()
        self._rows = []
        known = self._known()
        for title, icon, name in rows_for(self._hidden, self.config.entries, known):
            target = known.get(name)
            row = _Row(title, icon, widget_text(target) if target is not None else "")
            self._body_layout.addWidget(row)
            self._rows.append((row, name))
        if not self._rows:
            empty = QLabel("Totul încape în bară")
            empty.setProperty("class", "empty")
            self._body_layout.addWidget(empty)
        self._menu.adjustSize()

    def _refresh_values(self) -> None:
        if self._menu is None or not is_valid_qobject(self._menu) or not self._menu.isVisible():
            self._refresh.stop()
            return
        known = self._known()
        try:
            for row, name in self._rows:
                target = known.get(name)
                if target is not None:
                    row.value.setText(widget_text(target))
        except RuntimeError:
            logging.debug("bar_overflow: lista s-a inchis in timpul actualizarii")
            self._refresh.stop()
