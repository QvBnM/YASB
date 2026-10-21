from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel

# Cat de stransa e bara. Nivelul nu se alege din rezolutie si nici dintr-un prag de pixeli:
# se alege din ce cere chiar bara ta, cu widget-urile tale, masurat pe loc. Asa, acelasi
# config ajunge singur la nivelul potrivit pe orice ecran, fara nicio lista de rezolutii.
TIERS = ("min", "dense", "normal", "full")


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
    #
    # Cel mai stramt nivel la care bara are voie sa ajunga doar ca sa incapa tot. Sub el coboara
    # numai cand nici widget-urile de baza (ceasul, titlul ferestrei, starile) nu mai incap --
    # adica pe un ecran chiar ingust, unde ascunsul singur nu mai salveaza nimic.
    squeeze_to: Literal["min", "dense", "normal", "full"] = "normal"
    # Un ecran rotit are aceeasi problema ca un laptop, chiar daca numarul de pixeli zice altceva:
    # cu ceasul fixat la mijloc, 1080px latime lasa ~500px pe fiecare latura.
    portrait_max_tier: Literal["min", "dense", "normal", "full"] = "dense"
    # De la nivelul asta in jos, unitatile (%, grade) nu se mai scriu: cifra se intelege si fara.
    # Qt nu stie "display: none", deci ascunderea se face din cod, nu din stiluri.
    hide_units_from: Literal["min", "dense", "normal", "full"] = "dense"
