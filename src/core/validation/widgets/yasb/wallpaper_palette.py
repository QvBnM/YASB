from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig


class WallpaperPaletteMenuConfig(CustomBaseModel):
    blur: bool = False
    round_corners: bool = True
    round_corners_type: Literal["normal", "small"] = "normal"
    border_color: str = "None"
    alignment: Literal["left", "right", "center"] = "right"
    direction: Literal["up", "down"] = "down"
    offset_top: int = 6
    offset_left: int = 0


class WallpaperPaletteCallbacks(CallbacksConfig):
    on_left: str = "toggle_gallery"
    on_right: str = "next_wallpaper"


class WallpaperPaletteConfig(CustomBaseModel):
    label: str = "<span></span>"
    class_name: str = ""
    image_path: str | list[str]
    columns: int = Field(default=3, ge=1, le=6)
    thumb_width: int = Field(default=168, ge=80, le=400)
    max_images: int = Field(default=60, ge=1, le=500)
    visible_rows: int = Field(default=3, ge=1, le=10)
    # Comenzi rulate dupa schimbare; {path} = imaginea aleasa. Aici pui generatorul tau de paleta.
    run_after: list[str] = []
    auto_change: bool = False
    auto_change_minutes: int = Field(default=30, ge=1, le=1440)
    min_contrast: float = Field(default=4.5, ge=3.0, le=7.0)  # aceeasi regula ca yasb_palette.py
    title: str = "Wallpaper"
    auto_label: str = "Schimbă singur la {minutes} min"
    active_label: str = "Activ"
    menu: WallpaperPaletteMenuConfig = WallpaperPaletteMenuConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: WallpaperPaletteCallbacks = WallpaperPaletteCallbacks()
