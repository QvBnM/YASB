from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class AudioSliderIconsConfig(CustomBaseModel):
    muted: str = ""
    low: str = ""
    medium: str = ""
    high: str = ""


class AudioSliderConfig(CustomBaseModel):
    class_name: str = ""
    slider_width: int = Field(default=72, ge=24, le=400)
    show_value: bool = True
    show_icon: bool = True
    scroll_step: int = Field(default=2, ge=1, le=100)
    muted_text: str = "Mut"
    icons: AudioSliderIconsConfig = AudioSliderIconsConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: CallbacksConfig = CallbacksConfig()
