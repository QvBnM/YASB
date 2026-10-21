from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel


class ModeRule(CustomBaseModel):
    name: str  # devine clasa CSS "mode-<name>" pe bara
    processes: list[str] = []  # ex. ["Code.exe"], fara diferente intre litere mari/mici
    match: Literal["focused", "running"] = "focused"
    mic_in_use: bool = False  # True: modul porneste cand o aplicatie inregistreaza de la microfon
    skip_fullscreen: bool = True  # in fullscreen bara oricum dispare
    hide: list[str] = []  # widget-uri (nume din config.yaml) ascunse in modul asta
    show: list[str] = []  # widget-uri din hidden_by_default aratate in modul asta
    linger: int = Field(default=1500, ge=0)  # ms: ramane activ putin dupa alt-tab, ca bara sa nu sara


class ContextModeConfig(CustomBaseModel):
    interval: int = Field(default=700, ge=200)
    modes: list[ModeRule] = []  # prima regula care se potriveste castiga
    hidden_by_default: list[str] = []  # widget-uri care apar doar cand un mod le cere
    mic_ignore: list[str] = []  # aplicatii ignorate la detectia apelului
