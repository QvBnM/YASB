from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel
from core.validation.widgets.yasb.windows_desktops import WindowsDesktopsConfig


class DesktopsHoverConfig(CustomBaseModel):
    enabled: bool = True
    delay: int = Field(default=350, ge=0, le=3000)  # ms pana apare lista la hover
    max_icons: int = Field(default=6, ge=1, le=20)
    empty_label: str = "gol"
    name_format: str = "Desktop {index}"  # pentru desktop-urile fara nume


class DesktopsPlusConfig(WindowsDesktopsConfig):
    scan_interval: int = Field(default=1500, ge=500)  # ms intre verificarile ferestrelor
    ignore_processes: list[str] = ["TextInputHost.exe", "ShellExperienceHost.exe", "SearchHost.exe"]
    hover: DesktopsHoverConfig = DesktopsHoverConfig()
