from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class AudioOrbitMenuConfig(CustomBaseModel):
    blur: bool = False
    round_corners: bool = False
    round_corners_type: str = "normal"
    border_color: str = "None"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    width: int = Field(default=520, ge=360, le=1600)
    height: int = Field(default=480, ge=360, le=1400)
    font_family: str = "JetBrainsMono NF"
    show_input_tab: bool = True
    show_settings_node: bool = True
    animate_orbit: bool = False
    close_on_select: bool = False


class AudioOrbitColorsConfig(CustomBaseModel):
    # Hex colors; #AARRGGBB is accepted for transparency
    background: str = "#121a19"
    border: str = "#2a3836"
    accent: str = "#7dd9c7"
    on_accent: str = "#0f1716"
    card: str = "#141d1c"
    card_hover: str = "#1b2826"
    text: str = "#e6eceb"
    subtext: str = "#7f908d"
    muted: str = "#55615f"
    danger: str = "#e78a8a"


class AudioOrbitIconsConfig(CustomBaseModel):
    headphones: str = ""
    speakers: str = ""
    monitor: str = ""
    bluetooth: str = ""
    microphone: str = ""
    settings: str = ""
    muted: str = ""
    mic_muted: str = "\uf131"
    check: str = "\uf00c"
    unmuted: str = ""
    output_tab: str = ""
    input_tab: str = ""


class AudioOrbitLabelsConfig(CustomBaseModel):
    output: str = "Ieșire"
    input: str = "Intrare"
    active: str = "Activ"
    muted: str = "Mut"
    settings_title: str = "Setări sunet"
    settings_sub: str = "Panoul Windows"
    empty_title: str = "Niciun alt dispozitiv"
    empty_sub: str = "Conectează căști sau boxe"
    empty_sub_input: str = "Conectează un microfon"
    switch_hint: str = "Click pentru a comuta"
    set_badge: str = "SETAT"
    switched_badge: str = "COMUTAT"
    muted_badge: str = "MUT"
    no_device: str = "Fără ieșire audio"


class AudioOrbitCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"
    on_middle: str = "toggle_label"
    on_right: str = "toggle_mute"


class AudioOrbitConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {device}"
    label_alt: str = "<span>{icon}</span> {level}"
    class_name: str = ""
    max_device_chars: int = Field(default=18, ge=3, le=80)
    tooltip: bool = True
    scroll_step: int = Field(default=2, ge=1, le=100)
    switch_communications: bool = True
    # "palette": colors follow palette.json written by the wallpaper recolor script
    # (falls back to `colors` when the file is missing); "config": always use `colors`
    colors_source: Literal["config", "palette"] = "palette"
    palette_file: str = ""
    menu: AudioOrbitMenuConfig = AudioOrbitMenuConfig()
    colors: AudioOrbitColorsConfig = AudioOrbitColorsConfig()
    icons: AudioOrbitIconsConfig = AudioOrbitIconsConfig()
    labels: AudioOrbitLabelsConfig = AudioOrbitLabelsConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: AudioOrbitCallbacksConfig = AudioOrbitCallbacksConfig()
