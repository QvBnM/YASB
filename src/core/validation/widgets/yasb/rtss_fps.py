from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel


class RtssFpsCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"


class RtssFpsConfig(CustomBaseModel):
    label: str = "<span>FPS</span> {fps:>3}"
    label_alt: str = "<span>FT</span> {frametime:>4.1f}<span class='unit'>ms</span>"
    class_name: str = ""
    update_interval: int = Field(default=1000, ge=250)
    hide_if_unavailable: bool = True  # RivaTuner oprit sau niciun joc cu overlay
    foreground_only: bool = True  # doar jocul din fereastra activa, nu orice proces cu overlay
    callbacks: RtssFpsCallbacksConfig = RtssFpsCallbacksConfig()
