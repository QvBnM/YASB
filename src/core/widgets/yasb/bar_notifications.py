"""
Notificarile apar in bara, in locul titlului ferestrei, cateva secunde.

Clopotelul arata cate notificari necitite ai (ca widget-ul notifications din YASB).
Cand vine una noua, textul ei (expeditor + mesaj) apare in bara cu "Deschide" si "Ignoră".
Citirea foloseste UserNotificationListener din Windows: prima data Windows iti cere acordul
(Setari > Confidentialitate > Notificari). Toast-urile din coltul ecranului le poti opri
din Setari > Sistem > Notificari, daca vrei sa le vezi doar aici.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from core.events.service import EventService
from core.utils.system import is_windows_10
from core.utils.win32.system_function import notification_center, quick_settings
from core.validation.widgets.yasb.bar_notifications import BarNotificationsConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb.mint_common import fill_labels, find_named, set_class_token

try:
    from core.widgets.services.notifications.windows_notification import WindowsNotificationEventListener
except ImportError:
    WindowsNotificationEventListener = None
    logging.warning("bar_notifications: ascultatorul de notificari Windows nu e disponibil")


@dataclass
class Toast:
    id: int
    app: str
    aumid: str
    texts: list[str] = field(default_factory=list)

    @property
    def who(self) -> str:
        return self.texts[0] if self.texts else self.app

    @property
    def message(self) -> str:
        return " ".join(t.strip() for t in self.texts[1:] if t and t.strip())


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def _read_toasts() -> list[Toast]:
    import winrt.windows.ui.notifications.management as management
    from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds

    listener = management.UserNotificationListener.current
    items = await listener.get_notifications_async(NotificationKinds.TOAST)
    out: list[Toast] = []
    for n in items:
        try:
            app, aumid = "", ""
            try:
                app = n.app_info.display_info.display_name
                aumid = n.app_info.app_user_model_id
            except Exception:
                pass
            texts: list[str] = []
            binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
            if binding is not None:
                texts = [t.text for t in binding.get_text_elements()]
            out.append(Toast(int(n.id), app, aumid, texts))
        except Exception:
            logging.debug("bar_notifications: notificare ilizibila", exc_info=True)
    return out


async def _remove_toast(toast_id: int) -> None:
    import winrt.windows.ui.notifications.management as management

    management.UserNotificationListener.current.remove_notification(toast_id)


def _run_async(coro_factory, on_done=None) -> None:
    def work():
        try:
            result = asyncio.run(coro_factory())
        except Exception:
            logging.debug("bar_notifications: apel WinRT esuat", exc_info=True)
            result = None
        if on_done is not None:
            try:
                on_done(result)
            except RuntimeError:
                pass

    threading.Thread(target=work, name="mint-toasts", daemon=True).start()


class _Toast(QFrame):
    """Capsula din bara: expeditor, mesaj, Deschide, Ignoră."""

    def __init__(self, owner: BarNotificationsWidget):
        super().__init__()
        self.setProperty("class", "mint-toast")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.who = QLabel()
        self.who.setProperty("class", "who")
        self.msg = QLabel()
        self.msg.setProperty("class", "msg")
        self.open_btn = QPushButton(owner.config.open_label)
        self.open_btn.setProperty("class", "act")
        self.dismiss_btn = QPushButton(owner.config.dismiss_label)
        self.dismiss_btn.setProperty("class", "act dismiss")
        for w in (self.who, self.msg, self.open_btn, self.dismiss_btn):
            lay.addWidget(w)
        self._owner = owner
        self.open_btn.clicked.connect(owner._open_current)
        self.dismiss_btn.clicked.connect(owner._dismiss_current)
        self.hide()

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._owner._open_current()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._owner._hold(True)
        super().enterEvent(event)

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._owner._hold(False)
        super().leaveEvent(a0)


class BarNotificationsWidget(BaseWidget):
    validation_schema = BarNotificationsConfig
    event_listener = WindowsNotificationEventListener  # porneste serviciul YASB care numara notificarile
    _count_signal = pyqtSignal(int)
    _toasts_signal = pyqtSignal(object)

    def __init__(self, config: BarNotificationsConfig):
        super().__init__(class_name=f"bar-notifications-widget {config.class_name}")
        self.config = config
        self._count = 0
        self._seen: set[int] | None = None  # None = inca n-am citit lista initiala
        self._current: Toast | None = None
        self._capsule: _Toast | None = None
        self._target: QWidget | None = None
        self._target_was_visible = False
        self._ignored = {a.lower() for a in config.ignore_apps}

        self._init_container()
        self.build_widget_label(config.label)
        self.register_callback("toggle_notification", self._toggle_center)
        self.register_callback("clear_notifications", self._clear_all)
        self.register_callback("dismiss", self._dismiss_current)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_capsule)

        self._events = EventService()
        self._count_signal.connect(self._on_count)
        self._toasts_signal.connect(self._on_toasts)
        self._events.register_event("WindowsNotificationUpdate", self._count_signal)
        events, signal = self._events, self._count_signal  # fara referinte la self dupa distrugere
        self.destroyed.connect(lambda *_: events.unregister_event("WindowsNotificationUpdate", signal))

        self._render()
        QTimer.singleShot(1500, self._refresh_toasts)

    # ------------------------------------------------------------------ date

    def _on_count(self, count: int) -> None:
        grew = count > self._count
        self._count = count
        self._render()
        if grew or self._seen is None:
            self._refresh_toasts()

    def _refresh_toasts(self) -> None:
        _run_async(_read_toasts, self._toasts_signal.emit)

    def _on_toasts(self, toasts: list[Toast] | None) -> None:
        if toasts is None:
            return
        ids = {t.id for t in toasts}
        if self._seen is None:
            self._seen = ids  # ce era deja in centrul de notificari nu mai apare in bara
            return
        fresh = [t for t in toasts if t.id not in self._seen and t.app.lower() not in self._ignored]
        self._seen = ids | self._seen
        if fresh:
            self._show(max(fresh, key=lambda t: t.id))

    # ------------------------------------------------------------------ afisare

    def _render(self) -> None:
        icon = self.config.icons.new if self._count else self.config.icons.default
        fill_labels(self, {"icon": icon, "count": f" {self._count}" if self._count else ""})
        for lb in self._widgets:
            set_class_token(lb, "has-new", self._count > 0)

    def _ensure_capsule(self) -> _Toast:
        if self._capsule is not None:
            return self._capsule
        capsule = _Toast(self)
        root = self.window()
        targets = find_named([self.config.replace], root) if self.config.replace else []
        target = targets[0] if targets else None
        layout = target.parentWidget().layout() if target is not None and target.parentWidget() else None
        if target is not None and layout is not None and layout.indexOf(target) >= 0:
            layout.insertWidget(layout.indexOf(target), capsule)  # type: ignore[attr-defined]
            self._target = target
        else:
            self.widget_layout.addWidget(capsule)
        self._capsule = capsule
        return capsule

    def _show(self, toast: Toast) -> None:
        self._current = toast
        capsule = self._ensure_capsule()
        capsule.who.setText(shorten(toast.who, 28))
        msg = shorten(toast.message, self.config.max_chars)
        capsule.msg.setText(msg)
        capsule.msg.setVisible(bool(msg))
        capsule.open_btn.setVisible(bool(toast.aumid))
        if self._target is not None and not capsule.isVisible():
            self._target_was_visible = not self._target.isHidden()
            self._target.setVisible(False)
        capsule.show()
        self._hide_timer.start(self.config.duration * 1000)

    def _hide_capsule(self) -> None:
        if self._capsule is not None:
            self._capsule.hide()
        if self._target is not None and self._target_was_visible:
            self._target.setVisible(True)
        self._current = None

    def _hold(self, holding: bool) -> None:
        if holding:
            self._hide_timer.stop()
        elif self._capsule is not None and self._capsule.isVisible():
            self._hide_timer.start(2000)

    # ------------------------------------------------------------------ actiuni

    def _open_current(self) -> None:
        toast = self._current
        self._hide_capsule()
        if toast and toast.aumid:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{toast.aumid}"])

    def _dismiss_current(self) -> None:
        toast = self._current
        self._hide_capsule()
        if toast:
            _run_async(lambda: _remove_toast(toast.id))

    def _toggle_center(self) -> None:
        if is_windows_10():
            quick_settings()
        else:
            notification_center()

    def _clear_all(self) -> None:
        self._hide_capsule()
        self._events.emit_event("WindowsNotificationClear", "")
