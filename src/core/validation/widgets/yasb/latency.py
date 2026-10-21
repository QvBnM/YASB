from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel


class LatencyCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"


class LatencyConfig(CustomBaseModel):
    label: str = "<span>PING</span> {ms:>3}<span class='unit'>ms</span>"
    label_alt: str = "<span>PING</span> {host} {ms}<span class='unit'>ms</span>"
    class_name: str = ""
    host: str = "1.1.1.1"
    update_interval: int = Field(default=3000, ge=1000)
    timeout: int = Field(default=1000, ge=100, le=5000)
    callbacks: LatencyCallbacksConfig = LatencyCallbacksConfig()
