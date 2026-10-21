from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel


class ThresholdRule(CustomBaseModel):
    widget: str  # numele widget-ului din config.yaml (ex. "gpu")
    index: int | None = None  # a cata eticheta de text (0 = prima); None = toate
    pattern: str = r"(-?\d+(?:[.,]\d+)?)"  # primul numar din text
    warn: float
    crit: float
    below: bool = False  # True: avertizeaza cand valoarea scade SUB prag (ex. FPS)


class MintThresholdsConfig(CustomBaseModel):
    rules: list[ThresholdRule] = []
    rescan_interval: int = Field(default=3000, ge=500)
