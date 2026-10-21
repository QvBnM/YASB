from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel


class BarNotificationsIcons(CustomBaseModel):
    default: str = ""
    new: str = ""


class BarNotificationsCallbacks(CallbacksConfig):
    on_left: str = "toggle_notification"  # deschide centrul de notificari Windows
    on_right: str = "clear_notifications"


class BarNotificationsConfig(CustomBaseModel):
    label: str = "<span>{icon}</span>{count}"
    class_name: str = ""
    replace: str = "active_window"  # widget-ul ascuns cat timp se vede mesajul
    duration: int = Field(default=6, ge=2, le=60)  # secunde; mouse-ul peste mesaj il tine deschis
    max_chars: int = Field(default=70, ge=20, le=200)
    ignore_apps: list[str] = []  # nume afisate (ex. "Windows Security") pentru care nu apare nimic in bara
    open_label: str = "Deschide"
    dismiss_label: str = "Ignoră"
    icons: BarNotificationsIcons = BarNotificationsIcons()
    callbacks: BarNotificationsCallbacks = BarNotificationsCallbacks()
