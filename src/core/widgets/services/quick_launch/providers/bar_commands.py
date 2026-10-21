"""
Comenzile barei in lansatorul YASB (quick_launch).

Orice actiune pe care o face un widget la click se poate rula si din tastatura:
o comanda spune ce widget (numele din config.yaml) si ce callback sa ruleze,
sau ce program sa porneasca.

    providers:
      bar_commands:
        enabled: true
        commands:
          - { title: "Comută microfonul", icon: "", widget: "mic", callback: "toggle_mute" }
          - { title: "Pornește focus 25 min", widget: "focus", callback: "toggle_timer" }
          - { title: "Desktop 2", widget: "desktops", callback: "switch_desktop 2" }
          - { title: "Terminal", exec: "wt.exe" }
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.widgets.services.quick_launch.base_provider import BaseProvider, ProviderResult

__all__ = ["BarCommandsProvider"]


class _Dispatcher(QObject):
    """Primeste comenzile de pe firul lansatorului si le ruleaza pe firul interfetei."""

    run = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.run.connect(self._run)

    def _run(self, data: dict) -> None:
        if data.get("exec"):
            subprocess.Popen(data["exec"], shell=True)
            return
        name, callback = data.get("widget"), data.get("callback")
        if not name or not callback:
            return
        from core.widgets.base import BaseWidget

        candidates = []
        for top in QApplication.topLevelWidgets():
            for w in [top, *top.findChildren(BaseWidget)]:
                if isinstance(w, BaseWidget) and getattr(w, "widget_name", None) == name:
                    candidates.append(w)
        if not candidates:
            logging.warning("bar_commands: nu exista widget-ul '%s' in bara", name)
            return
        # widget-ul de pe monitorul cu mouse-ul, altfel primul
        from PyQt6.QtGui import QCursor

        screen = QApplication.screenAt(QCursor.pos())
        target = next((w for w in candidates if w.isVisible() and w.screen() is screen), None) or candidates[0]
        try:
            target._run_callback(callback)
        except Exception:
            logging.exception("bar_commands: '%s' pe '%s' a esuat", callback, name)


_dispatcher: _Dispatcher | None = None


def _matches(query: str, title: str, keywords: str) -> bool:
    hay = f"{title} {keywords}".casefold()
    return all(word in hay for word in query.casefold().split())


class BarCommandsProvider(BaseProvider):
    name = "bar_commands"
    display_name = "Comenzi bară"
    input_placeholder = "Comandă..."

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        global _dispatcher
        if _dispatcher is None:
            _dispatcher = _Dispatcher()  # creat pe firul interfetei, odata cu lansatorul
        self.commands: list[dict[str, Any]] = list(self.config.get("commands") or [])

    def get_results(self, text: str, **kwargs: Any) -> list[ProviderResult]:
        query = self.get_query_text(text)
        if not query and not self.prefix:
            return []  # fara prefix, nu umplem lista goala a lansatorului
        results = []
        for i, cmd in enumerate(self.commands):
            title = cmd.get("title", "")
            if query and not _matches(query, title, cmd.get("keywords", "")):
                continue
            results.append(
                ProviderResult(
                    title=title,
                    description=cmd.get("description", "") or "Comandă bară",
                    icon_char=cmd.get("icon", "") or "",
                    provider=self.name,
                    id=f"bar_commands:{i}",
                    action_data={k: cmd.get(k, "") for k in ("widget", "callback", "exec")},
                )
            )
        return results

    def execute(self, result: ProviderResult) -> bool | None:
        if _dispatcher is not None:
            _dispatcher.run.emit(dict(result.action_data))
        return True
