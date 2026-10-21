from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel


class ResponsiveConfig(CustomBaseModel):
    class_name: str = ""
    # what disappears first when a side of the bar runs out of room (names from config.yaml).
    # They come back, in reverse order, as soon as there is room again.
    hide_left: list[str] = ["viz", "git_branch", "volume_slider", "media", "notif"]
    hide_right: list[str] = ["wallpaper", "vram", "latency", "gpu", "net_group", "weather", "ram", "tray"]
    # widgets that shrink by themselves (the window title): only their minimum counts
    flexible: dict[str, int] = {"active_window": 110}
    # pixels kept free between a side and the clock
    margin: int = Field(default=16, ge=0, le=200)
    # extra room needed before something hidden comes back (no flickering)
    hysteresis: int = Field(default=24, ge=0, le=200)
    # bar narrower than this (logical px, after Windows scaling) -> class "compact" (tighter spacing)
    compact_below: int = Field(default=1800, ge=0)
    interval: int = Field(default=1000, ge=250, le=10000)
