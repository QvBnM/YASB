"""
Praguri de culoare pentru orice widget care afiseaza un numar.

Widget invizibil. Pentru fiecare regula din config, gaseste etichetele widget-ului tinta
si le pune clasa CSS `warn` sau `crit` cand numarul trece pragul. Clasa e recalculata
chiar in momentul in care widget-ul isi schimba textul, deci culoarea nu clipeste
(widget-urile YASB isi rescriu clasa la fiecare actualizare).

    mint_thresholds:
      type: "yasb.mint_thresholds.MintThresholdsWidget"
      options:
        rules:
          - { widget: "gpu", index: 1, warn: 80, crit: 90 }   # a doua cifra = temperatura
"""

from __future__ import annotations

import logging
import re

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel

from core.utils.utilities import refresh_widget_style
from core.validation.widgets.yasb.mint_thresholds import MintThresholdsConfig, ThresholdRule
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_text
from core.widgets.yasb.mint_common import find_named, make_invisible

_LEVELS = ("warn", "crit")


def evaluate(text: str, rules: list[ThresholdRule]) -> str | None:
    """Cel mai grav nivel ("crit" > "warn") dat de reguli pentru textul unei etichete."""
    worst: str | None = None
    for rule in rules:
        m = re.search(rule.pattern, text or "")
        if not m:
            continue
        try:
            value = float((m.group(1) if m.groups() else m.group(0)).replace(",", "."))
        except ValueError:
            continue
        if rule.below:
            level = "crit" if value <= rule.crit else "warn" if value <= rule.warn else None
        else:
            level = "crit" if value >= rule.crit else "warn" if value >= rule.warn else None
        if level == "crit":
            return "crit"
        if level == "warn":
            worst = "warn"
    return worst


def with_level(class_value: str, level: str | None) -> str:
    tokens = [t for t in (class_value or "").split() if t not in _LEVELS]
    if level:
        tokens.append(level)
    return " ".join(tokens)


def _text_labels(widget: BaseWidget) -> list[list[QLabel]]:
    groups = []
    for attr in ("_widgets", "_widgets_alt"):
        labels = getattr(widget, attr, None) or []
        groups.append([lb for lb in labels if isinstance(lb, QLabel) and "label" in (lb.property("class") or "").split()])
    return groups


def hook_label(label: QLabel, rule: ThresholdRule) -> None:
    rules: list[ThresholdRule] | None = getattr(label, "_mint_rules", None)
    if rules is not None:
        if rule not in rules:
            rules.append(rule)
        return
    label._mint_rules = [rule]  # type: ignore[attr-defined]
    orig_set_property = label.setProperty

    def set_property(name, value):
        # widget-urile YASB isi rescriu clasa la fiecare actualizare si ne-ar sterge culoarea
        if name == "class" and isinstance(value, str):
            value = with_level(value, evaluate(label.text(), label._mint_rules))  # type: ignore[attr-defined]
        return orig_set_property(name, value)

    def recolour(text: str) -> None:
        current = label.property("class") or ""
        new = with_level(current, evaluate(text, label._mint_rules))  # type: ignore[attr-defined]
        if new != current:
            orig_set_property("class", new)
            refresh_widget_style(label)

    # Widget-urile YASB apeleaza label.setProperty din Python, deci atributul de instanta
    # are prioritate fata de metoda Qt.
    label.setProperty = set_property  # type: ignore[method-assign]
    # Culoarea se calculeaza pe textul care chiar se vede, dupa traducere si taiere
    # (vezi mint_text): nu mai depinde de cine a ajuns primul la eticheta.
    mint_text.add_observer(label, "thresholds", recolour)


class MintThresholdsWidget(BaseWidget):
    validation_schema = MintThresholdsConfig

    def __init__(self, config: MintThresholdsConfig):
        super().__init__(class_name="mint-thresholds")
        self.config = config
        make_invisible(self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scan)
        self._timer.start(config.rescan_interval)
        QTimer.singleShot(500, self._scan)

    def _scan(self) -> None:
        root = self.window()
        if root is None or root is self:
            return
        for rule in self.config.rules:
            for widget in find_named([rule.widget], root):
                try:
                    for labels in _text_labels(widget):
                        targets = labels if rule.index is None else labels[rule.index : rule.index + 1]
                        for label in targets:
                            hook_label(label, rule)
                except Exception:
                    logging.exception("mint_thresholds: nu pot lega regula pentru %s", rule.widget)
