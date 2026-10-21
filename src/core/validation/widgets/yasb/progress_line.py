from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel


class QbittorrentConfig(CustomBaseModel):
    enabled: bool = False
    url: str = "http://localhost:8080"  # Web UI din qBittorrent; bifeaza "Bypass authentication for clients on localhost"
    interval: int = Field(default=3000, ge=1000)


class ProgressLineConfig(CustomBaseModel):
    height: int = Field(default=2, ge=1, le=6)
    position: Literal["bottom", "top"] = "bottom"
    sources: list[Literal["pomodoro", "media", "qbittorrent"]] = ["pomodoro", "media", "qbittorrent"]
    # culoarea fiecarei surse = numele unei variabile din palette.css
    colors: dict[str, str] = {"media": "accent", "pomodoro": "accent2", "qbittorrent": "warn"}
    pick: Literal["latest", "order"] = "latest"  # cea pornita cel mai recent, sau prima din lista
    media_paused: bool = False  # True: linia ramane si cand melodia e pe pauza
    qbittorrent: QbittorrentConfig = QbittorrentConfig()
