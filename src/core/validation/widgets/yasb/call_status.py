from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel


class CallStatusConfig(CustomBaseModel):
    label: str = "<span></span> În apel {elapsed}"
    label_alt: str = "<span></span> {app} {elapsed}"
    class_name: str = ""
    update_interval: int = Field(default=1000, ge=500)
    ignore: list[str] = []  # aplicatii care folosesc microfonul fara sa fie un apel
    grace: int = Field(default=4, ge=0)  # secunde: o pauza scurta de microfon nu reseteaza timpul
    callbacks: CallbacksConfig = CallbacksConfig(on_left="toggle_label")
