from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class NetStatusIconsConfig(CustomBaseModel):
    # Glifele astea sunt din setul Material Design al fontului, nu din Font Awesome ca restul
    # barei. E o alegere, nu o scapare: Font Awesome 4.7 (cat intra in Nerd Font) nu are
    # perechi pornit/oprit pentru Wi-Fi si Bluetooth, iar aici tocmai starea e ce conteaza.
    # Daca se schimba vreodata, se schimba toate sapte odata, ca sa ramana un set.
    ethernet: str = "\U000f0200"
    wifi: str = "\U000f05a9"
    wifi_off: str = "\U000f05aa"
    offline: str = "\U000f0c9b"
    bluetooth: str = "\U000f00af"
    bluetooth_off: str = "\U000f00b2"
    speed: str = "\U000f04c5"


class NetStatusMenuConfig(CustomBaseModel):
    blur: bool = False
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "None"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    show_speedtest: bool = True


class NetStatusCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"
    on_right: str = "toggle_label"


class NetStatusConfig(CustomBaseModel):
    class_name: str = ""
    # {icon} {name} (Cablu / SSID / Offline) {ip} {speed} (link speed) {adapter}
    label: str = "<span>{icon}</span>"
    label_alt: str = "<span>{icon}</span> {name}"
    update_interval: int = Field(default=3000, ge=1000, le=60000)
    tooltip: bool = True
    icons: NetStatusIconsConfig = NetStatusIconsConfig()
    menu: NetStatusMenuConfig = NetStatusMenuConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: NetStatusCallbacksConfig = NetStatusCallbacksConfig()


class SpeedtestCallbacksConfig(CallbacksConfig):
    on_left: str = "run_test"
    on_right: str = "toggle_label"


class SpeedtestConfig(CustomBaseModel):
    class_name: str = ""
    # {result} = "↓312 ↑45" / "test" / "testez…" / "eroare"; {down} {up} {ping} {time}
    label: str = "<span>\U000f04c5</span> {result}"
    label_alt: str = "<span>\U000f04c5</span> {ping}"
    tooltip: bool = True
    keybindings: list[KeybindingConfig] = []
    callbacks: SpeedtestCallbacksConfig = SpeedtestCallbacksConfig()
