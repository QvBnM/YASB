from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel


class OverflowEntry(CustomBaseModel):
    """Un rand din lista care apare cand bara e prea ingusta."""

    widget: str  # numele din config.yaml al widget-ului ascuns
    title: str = ""  # cum il numim in lista; gol = numele widget-ului
    icon: str = ""


class OverflowMenuConfig(CustomBaseModel):
    blur: bool = False
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "None"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0


class BarOverflowCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"


class BarOverflowConfig(CustomBaseModel):
    class_name: str = ""
    label: str = "<span>{icon}</span>"
    icon: str = ""  # sageata dubla, din aceeasi familie cu restul barei

    # Ce se arata in lista. Gol = tot ce a ascuns bara, in ordinea in care le-a ascuns.
    entries: list[OverflowEntry] = []

    # Cat de des se reciteste textul cat timp lista e deschisa (ms).
    refresh_interval: int = Field(default=1000, ge=250, le=10000)

    menu: OverflowMenuConfig = OverflowMenuConfig()
    callbacks: BarOverflowCallbacksConfig = BarOverflowCallbacksConfig()
