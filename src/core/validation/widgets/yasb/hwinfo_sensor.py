from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class HwinfoSensorCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"


class HwinfoSensorConfig(CustomBaseModel):
    class_name: str = ""
    # {value} {min} {max} {avg} {unit} {label} {sensor}
    label: str = "{value}{unit}"
    label_alt: str = "{label}: {value}{unit} (min {min} / max {max})"
    # first reading whose label contains one of these (case-insensitive), in order
    match: list[str] = [
        "CPU Package",
        "CPU (Tctl/Tdie)",
        "CPU Die (average)",
        "Core Max",
        "CPU",
    ]
    reading_type: Literal["temperature", "voltage", "fan", "current", "power", "clock", "usage", "other", "any"] = (
        "temperature"
    )
    sensor_match: str = ""  # optional: only sensors whose name contains this
    precision: int = Field(default=0, ge=0, le=3)
    # pad numbers to this many characters (monospace font -> the width never changes)
    value_width: int = Field(default=0, ge=0, le=8)
    update_interval: int = Field(default=2000, ge=500, le=60000)
    hide_if_unavailable: bool = True
    unavailable_label: str = "—"
    tooltip: bool = True
    # When HWiNFO stops sharing (free version: after 12 hours) or is closed, run this scheduled
    # task (created by tools/hwinfo_setup.ps1) to restart it. "" = never restart.
    restart_task: str = "YASB HWiNFO"
    restart_after: int = Field(default=90, ge=20, le=3600)  # seconds without data before restarting
    restart_every: int = Field(default=900, ge=60, le=86400)  # at most one restart per this many seconds
    keybindings: list[KeybindingConfig] = []
    callbacks: HwinfoSensorCallbacksConfig = HwinfoSensorCallbacksConfig()
