"""
Fake Qt and YASB modules, so the bar's logic can be tested without Windows and without PyQt6.

The widgets import PyQt6 and a dozen YASB modules at import time, but the functions worth
testing (which widget to hide, when a number is over its threshold, where a maximised window
belongs, how to read the sensor buffers) touch none of them. Here we put permissive stand-ins
in sys.modules before the widgets are imported, so the import succeeds and the real functions
run unchanged.

Only modules that YASB owns are faked. `core`, `core.widgets`, `core.widgets.yasb`,
`core.validation` and `core.widgets.services` are real folders in this repo and stay real
namespace packages, so the mint widgets and their schemas are imported from source.

install() must be called before importing anything from core.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


class _AutoMeta(type):
    """A class whose unknown attributes become classes too: Qt.WindowType.ToolTip and friends."""

    def __getattr__(cls, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        sub = _AutoMeta(name, (Auto,), {})
        setattr(cls, name, sub)
        return sub


class Auto(metaclass=_AutoMeta):
    """Stands in for any Qt class: can be constructed, called, subclassed and read from."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return Auto()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Auto()


def _auto_attr(mod: types.ModuleType, attr: str):
    if attr.startswith("__"):
        raise AttributeError(attr)
    value = _AutoMeta(attr, (Auto,), {})
    setattr(mod, attr, value)
    return value


def _fake(name: str, **attrs) -> types.ModuleType:
    """Put a stand-in module at `name`, without disturbing its real parent package."""
    mod = types.ModuleType(name)
    mod.__path__ = []  # type: ignore[attr-defined]  # so submodules can be injected under it
    for key, value in attrs.items():
        setattr(mod, key, value)
    mod.__getattr__ = lambda attr, _m=mod: _auto_attr(_m, attr)  # type: ignore[attr-defined]
    sys.modules[name] = mod
    parent, _, leaf = name.rpartition(".")
    if parent:
        try:
            setattr(importlib.import_module(parent), leaf, mod)
        except ImportError:
            pass  # parent is itself a stand-in that has not been created yet
    return mod


# YASB modules that do not exist in this repo and must be stood in for.
# Everything NOT listed here is imported from src/ for real.
_MISSING_SUBMODULES = (
    "core.config",
    "core.events",
    "core.events.service",
    "core.utils",
    "core.utils.qobject",
    "core.utils.tooltip",
    "core.utils.utilities",
    "core.utils.system",
    "core.utils.win32",
    "core.utils.win32.system_function",
    "core.utils.win32.constants",
    "core.utils.win32.bindings",
    "core.utils.win32.bindings.ole32",
    "core.utils.win32.bindings.shell32",
    "core.widgets.base",
    "core.widgets.services.media",
    "core.widgets.services.media.media",
    "core.widgets.services.volume",
    "core.widgets.services.volume.service",
    "core.widgets.services.microphone",
    "core.widgets.services.microphone.service",
    "core.widgets.services.windows_desktops",
    "core.widgets.services.windows_desktops.service",
    "core.widgets.services.notifications",
    "core.widgets.services.notifications.windows_notification",
    "core.widgets.services.taskbar",
    "core.widgets.services.taskbar.application_window",
    "core.widgets.yasb.bluetooth",
    "core.widgets.yasb.active_window",
    "core.widgets.yasb.audio_visualizer",
    "core.widgets.yasb.windows_desktops",
    "core.widgets.yasb.pomodoro",
    "core.widgets.yasb.clock",
    "core.widgets.yasb.media",
    "core.widgets.yasb.media_lite",
    "core.validation.widgets.base_model",
    "core.validation.widgets.yasb.windows_desktops",
    "core.validation.widgets.yasb.active_window",
    "core.validation.widgets.yasb.audio_visualizer",
    "core.widgets.services.quick_launch.base_provider",
)

_installed = False


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    # ---- PyQt6 and the few third-party packages the widgets import at module level
    _fake("PyQt6")
    for sub in ("QtCore", "QtGui", "QtWidgets"):
        _fake(f"PyQt6.{sub}")
    for name in ("comtypes", "pycaw", "pycaw.pycaw", "psutil", "winrt"):
        _fake(name)

    # ---- YASB's own modules
    for name in _MISSING_SUBMODULES:
        _fake(name)

    # The validation base models are real pydantic models, so this repo's own schemas really
    # validate. YASB's own schemas are only approximated (permissive), so a passing config test
    # proves the mint options are correct, not that every YASB option is.
    from pydantic import BaseModel, ConfigDict

    class CustomBaseModel(BaseModel):
        model_config = ConfigDict(extra="forbid", populate_by_name=True)

    class _Permissive(BaseModel):
        model_config = ConfigDict(extra="allow")

    class CallbacksConfig(_Permissive):
        on_left: str = "do_nothing"
        on_middle: str = "do_nothing"
        on_right: str = "do_nothing"

    class KeybindingConfig(_Permissive):
        keys: str = ""
        action: str = ""

    base_model = sys.modules["core.validation.widgets.base_model"]
    base_model.CustomBaseModel = CustomBaseModel  # type: ignore[attr-defined]
    base_model.CallbacksConfig = CallbacksConfig  # type: ignore[attr-defined]
    base_model.KeybindingConfig = KeybindingConfig  # type: ignore[attr-defined]

    for module_name, class_name in (
        ("core.validation.widgets.yasb.windows_desktops", "WindowsDesktopsConfig"),
        ("core.validation.widgets.yasb.active_window", "ActiveWindowConfig"),
        ("core.validation.widgets.yasb.audio_visualizer", "AudioVisualizerConfig"),
    ):
        setattr(sys.modules[module_name], class_name, type(class_name, (_Permissive,), {}))

    provider = sys.modules["core.widgets.services.quick_launch.base_provider"]
    provider.BaseProvider = _AutoMeta("BaseProvider", (Auto,), {})  # type: ignore[attr-defined]
    provider.ProviderResult = _AutoMeta("ProviderResult", (Auto,), {})  # type: ignore[attr-defined]

    sys.modules["core.widgets.base"].BaseWidget = _AutoMeta("BaseWidget", (Auto,), {})  # type: ignore[attr-defined]
    sys.modules["core.config"].get_config_dir = lambda: str(Path.home() / ".config" / "yasb")  # type: ignore[attr-defined]
    sys.modules["core.utils.qobject"].is_valid_qobject = lambda _o: True  # type: ignore[attr-defined]
    sys.modules["core.utils.tooltip"].set_tooltip = lambda *_a, **_k: None  # type: ignore[attr-defined]
    sys.modules["core.utils.utilities"].refresh_widget_style = lambda *_a, **_k: None  # type: ignore[attr-defined]
    sys.modules["core.utils.system"].is_windows_10 = lambda: False  # type: ignore[attr-defined]
