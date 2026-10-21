from pydantic import Field

from core.validation.widgets.yasb.active_window import ActiveWindowConfig


class ActiveTitleConfig(ActiveWindowConfig):
    # the title fills the free space up to the clock (or the bar's center) and is cut with "…"
    gap: int = Field(default=24, ge=0, le=400)  # free pixels kept before the clock
    min_width: int = Field(default=60, ge=0)  # never shorter than this
