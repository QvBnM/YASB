from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel


class CoverAccentConfig(CustomBaseModel):
    targets: list[str] = ["media_group", "desktops"]  # widget-uri (nume din config.yaml) care iau culoarea
    min_contrast: float = Field(default=3.0, ge=1.5, le=7.0)  # fata de --bar, ca accentul sa ramana lizibil
    transition: int = Field(default=400, ge=0, le=3000)  # ms
    keep_on_pause: bool = False  # True: culoarea ramane si pe pauza
    min_saturation: float = Field(default=0.18, ge=0.0, le=1.0)  # coperta alb-negru = ramane paleta
