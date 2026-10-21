from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel

# Cat de stransa e bara. Nivelul se alege din spatiul ramas pe o latura, nu din rezolutia
# ecranului: asa, un monitor mare scalat la 150% si un laptop mic ajung singure la acelasi
# nivel, fara nicio setare scrisa pe undeva.
TIERS = ("min", "dense", "normal", "full")


class TierThresholds(CustomBaseModel):
    """Spatiul liber (px logici) de la care in sus bara trece la nivelul urmator."""

    full: int = Field(default=820, ge=0)
    normal: int = Field(default=560, ge=0)
    dense: int = Field(default=360, ge=0)


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
    interval: int = Field(default=1000, ge=250, le=10000)

    # Nivelurile pun pe bara clasa "tier-<nume>", folosita in styles.css pentru spatieri mai
    # stranse si text mai mic. Sub "full" se pune si clasa "compact", ca regulile vechi sa tina.
    tiers: TierThresholds = TierThresholds()
    # Un ecran rotit are aceeasi problema ca un laptop, chiar daca numarul de pixeli zice altceva:
    # cu ceasul fixat la mijloc, 1080px latime lasa ~500px pe fiecare latura.
    portrait_max_tier: Literal["min", "dense", "normal", "full"] = "dense"
    # De la nivelul asta in jos, unitatile (%, grade) nu se mai scriu: cifra se intelege si fara.
    # Qt nu stie "display: none", deci ascunderea se face din cod, nu din stiluri.
    hide_units_from: Literal["min", "dense", "normal", "full"] = "dense"
