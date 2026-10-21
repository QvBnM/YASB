"""
Moduri automate: bara isi schimba continutul dupa ce faci.

Widget invizibil. La fiecare `interval` ms verifica fereastra activa, procesele pornite
si daca vreo aplicatie inregistreaza de la microfon. Prima regula din `modes` care se
potriveste devine modul curent:
  - ascunde widget-urile din `hide`, arata widget-urile din `show`
    (cele din `hidden_by_default` stau ascunse cand niciun mod nu le cere);
  - pune clasa "mode-<nume>" pe bara, pentru reguli CSS de tipul `.mode-game .clock-widget`.

Widget-urile pe care nu le-a ascuns el nu le atinge: daca un widget se ascunde singur
(Bluetooth fara modul, vizualizatorul fara muzica), ramane cum a vrut el.
"""

from __future__ import annotations

import logging
import os
import time

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from core.events.service import EventService
from core.validation.widgets.yasb.context_mode import ContextModeConfig, ModeRule
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb import mint_health as health
from core.widgets.yasb.mint_common import (
    Foreground,
    all_bar_widgets,
    foreground,
    make_invisible,
    mic_users,
    refresh_tree,
    running_process_names,
    set_class_token,
)

class ContextModeWidget(BaseWidget):
    validation_schema = ContextModeConfig
    mode_changed = pyqtSignal(str)

    def __init__(self, config: ContextModeConfig):
        super().__init__(class_name="context-mode")
        self.config = config
        make_invisible(self)

        self._mode: str | None = "<start>"
        self._last_true: dict[str, float] = {}
        self._last_fg = Foreground()
        self._running: set[str] = set()
        self._bar_frame: QWidget | None = None
        self._need_running = any(r.match == "running" and r.processes for r in config.modes)
        self._need_mic = any(r.mic_in_use for r in config.modes)

        self._events = EventService()
        self._timer = QTimer(self)
        health.connect(self._timer, "modes", self._tick)
        self._timer.start(config.interval)
        QTimer.singleShot(300, self._tick)

    # ------------------------------------------------------------------ detectie

    def _matches(self, rule: ModeRule, fg: Foreground, mic: list[str]) -> bool:
        has_condition = False
        if rule.processes:
            has_condition = True
            names = {p.lower() for p in rule.processes}
            if rule.match == "focused":
                if rule.skip_fullscreen and fg.fullscreen:
                    return False
                if fg.exe.lower() not in names:
                    return False
            elif not (names & self._running):
                return False
        if rule.mic_in_use:
            has_condition = True
            if not mic:
                return False
        return has_condition

    def _tick(self) -> None:
        try:
            fg = foreground()
            # click pe bara = fereastra activa e YASB; pastram ce era inainte
            if fg.pid and fg.pid == os.getpid():
                fg = self._last_fg
            else:
                self._last_fg = fg

            now = time.monotonic()
            # amandoua isi tin singure ultimul raspuns cateva momente (vezi ttl_cache),
            # deci pe mai multe monitoare munca se face o singura data
            self._running = running_process_names() if self._need_running else set()
            mic = mic_users(self.config.mic_ignore) if self._need_mic else []

            chosen: ModeRule | None = None
            for rule in self.config.modes:
                if self._matches(rule, fg, mic):
                    self._last_true[rule.name] = now
                    chosen = rule
                    break
                if (now - self._last_true.get(rule.name, -1e9)) * 1000 < rule.linger:
                    chosen = rule
                    break
            self._apply(chosen)
        except Exception as exc:
            health.failed("modes", exc, self._timer.stop)

    # ------------------------------------------------------------------ aplicare

    def _find_bar_frame(self, root: QWidget) -> QWidget:
        # referinta tinuta minte poate fi de la o bara disparuta (alt monitor, alta configurare)
        if self._bar_frame is not None and self._bar_frame.parent() is not None:
            return self._bar_frame
        for w in [root, *root.findChildren(QWidget)]:
            if "yasb-bar" in (w.property("class") or "").split():
                self._bar_frame = w
                return w
        self._bar_frame = root
        return root

    def _apply(self, rule: ModeRule | None) -> None:
        root = self.window()
        if root is None or root is self:
            return
        name = rule.name if rule else None

        hidden = set(self.config.hidden_by_default)
        if rule:
            hidden |= set(rule.hide)
            hidden -= set(rule.show)

        # Nu chemam setVisible: spunem doar parerea noastra. Daca widget-ul n-are ce arata,
        # sau daca nu mai incape pe bara, hotararea lor ramane in picioare (vezi mint_visibility).
        for w in all_bar_widgets(root):
            wname = getattr(w, "widget_name", None)
            if not wname or w is self:
                continue
            visibility.request(w, visibility.MODE, wname not in hidden)

        if name != self._mode:
            self._mode = name
            frame = self._find_bar_frame(root)
            set_class_token(frame, f"mode-{name}" if name else "mode-none", True, prefix="mode-")
            refresh_tree(frame)
            self.mode_changed.emit(name or "")
            self._events.emit_event("MintModeChanged", name or "")
            logging.info("context_mode: mod %s", name or "implicit")
