"""
AudioOrbit widget: pick the audio output (or input) device from a radial,
"orbit" style popup. The active device sits in the centre with a volume ring;
every other device floats around it — click one to make it the default.
"""

import json
import logging
import os
import re
import threading

import comtypes
from pycaw.pycaw import AudioUtilities, ERole
from PyQt6.QtCore import QFileSystemWatcher, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from core.utils.qobject import is_valid_qobject
from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.audio_orbit import AudioOrbitConfig
from core.widgets.base import BaseWidget
from core.widgets.services.microphone.service import AudioInputService
from core.widgets.services.volume.service import AudioOutputService
from core.widgets.yasb.audio_orbit_canvas import OrbitCanvas, OrbitDevice


class AudioOrbitWidget(BaseWidget):
    validation_schema = AudioOrbitConfig
    _switch_done = pyqtSignal(str, bool)

    def __init__(self, config: AudioOrbitConfig):
        super().__init__(class_name=f"audio-orbit-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._mode = "output"
        self.dialog: PopupWidget | None = None
        self.canvas: OrbitCanvas | None = None
        self._switching = False

        # Windows fires one notification per audio role (and per volume tick);
        # coalesce them so the UI refreshes once instead of 3-4 times.
        self._device_timer = self._make_debounce(140, self._apply_device_change)
        self._volume_timer = self._make_debounce(24, self._apply_volume_change)
        self._switch_done.connect(self._on_switch_done)

        # Wallpaper palette (palette.json from the recolor script): follow it live
        self._palette: dict[str, str] = {}
        self._palette_watcher: QFileSystemWatcher | None = None
        if self.config.colors_source == "palette":
            self._palette_path = self._resolve_palette_path()
            self._palette_timer = self._make_debounce(250, self._reload_palette)
            self._palette_watcher = QFileSystemWatcher(self)
            folder = os.path.dirname(self._palette_path)
            if os.path.isdir(folder):
                self._palette_watcher.addPath(folder)
            if os.path.isfile(self._palette_path):
                self._palette_watcher.addPath(self._palette_path)
            self._palette_watcher.directoryChanged.connect(lambda _p: self._palette_timer.start())
            self._palette_watcher.fileChanged.connect(lambda _p: self._palette_timer.start())
            self._reload_palette()

        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)

        self.register_callback("toggle_menu", self._toggle_menu)
        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("toggle_mute", self._toggle_output_mute)

        self.callback_left = self.config.callbacks.on_left
        self.callback_right = self.config.callbacks.on_right
        self.callback_middle = self.config.callbacks.on_middle

        self._out = AudioOutputService()
        self._out.register_widget(self)
        self._in: AudioInputService | None = None
        if self.config.menu.show_input_tab:
            self._in = AudioInputService()
            self._in.register_widget(self)
        self.destroyed.connect(self._unregister_services)

        self._update_label()

    # --------------------------------------------------------------- palette

    def _resolve_palette_path(self) -> str:
        if self.config.palette_file:
            return os.path.expandvars(os.path.expanduser(self.config.palette_file))
        base = os.environ.get("YASB_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config", "yasb")
        return os.path.join(base, "palette.json")

    def _reload_palette(self) -> None:
        try:
            with open(self._palette_path, encoding="utf-8") as f:
                data = json.load(f)
            colors = data.get("orbit", data)
            self._palette = {k: v for k, v in colors.items() if isinstance(v, str) and v.startswith("#")}
        except Exception:  # missing / partial / invalid file
            self._palette = {}
        if self._palette_watcher is not None and os.path.isfile(self._palette_path):
            if self._palette_path not in self._palette_watcher.files():
                self._palette_watcher.addPath(self._palette_path)
        if self._canvas_alive():
            self.canvas.set_colors(self._colors())

    def _colors(self) -> dict[str, str]:
        return {**self.config.colors.model_dump(), **self._palette}

    def _unregister_services(self) -> None:
        try:
            self._out.unregister_widget(self)
            if self._in:
                self._in.unregister_widget(self)
        except Exception:
            pass

    # ---------------------------------------------------- service listeners

    def _make_debounce(self, ms: int, slot) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(ms)
        t.timeout.connect(slot)
        return t

    def on_output_volume_changed(self) -> None:
        self._volume_timer.start()

    def on_output_device_changed(self) -> None:
        self._device_timer.start()

    def on_input_volume_changed(self) -> None:
        self._volume_timer.start()

    def on_input_device_changed(self) -> None:
        self._device_timer.start()

    def _apply_volume_change(self) -> None:
        self._update_label()
        if self._canvas_alive():
            self.canvas.set_volume(*self._read_volume(self._mode))

    def _apply_device_change(self) -> None:
        self._update_label()
        if self._canvas_alive() and not self._switching:
            self._refresh_canvas()

    # ------------------------------------------------------------- helpers

    def _canvas_alive(self) -> bool:
        return self.canvas is not None and is_valid_qobject(self.canvas)

    def _service(self, mode: str):
        return self._in if mode == "input" and self._in else self._out

    def _volume_iface(self, mode: str):
        if mode == "input" and self._in:
            return self._in.get_microphone_interface()
        return self._out.get_volume_interface()

    def _read_volume(self, mode: str) -> tuple[float, bool]:
        iface = self._volume_iface(mode)
        if iface is None:
            return 0.0, False
        try:
            return float(iface.GetMasterVolumeLevelScalar()), bool(iface.GetMute())
        except Exception:
            return 0.0, False

    def _devices(self, mode: str) -> list[OrbitDevice]:
        is_input = mode == "input"
        return [OrbitDevice.from_friendly(i, n, is_input=is_input) for i, n in self._service(mode).get_all_devices()]

    def _active_output(self) -> OrbitDevice | None:
        active_id = self._out.get_default_device_id()
        for dev in self._devices("output"):
            if dev.id == active_id:
                return dev
        return None

    # --------------------------------------------------------------- label

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for w in self._widgets:
            w.setVisible(not self._show_alt_label)
        for w in self._widgets_alt:
            w.setVisible(self._show_alt_label)
        self._update_label()

    def _update_label(self) -> None:
        widgets = self._widgets_alt if self._show_alt_label else self._widgets
        content = self.config.label_alt if self._show_alt_label else self.config.label
        parts = [p for p in re.split(r"(<span.*?>.*?</span>)", content) if p and p.strip()]

        dev = self._active_output()
        vol, muted = self._read_volume("output")
        icons = self.config.icons
        if dev is None:
            icon, name, level = icons.speakers, self.config.labels.no_device, "—"
        else:
            icon = icons.muted if muted else getattr(icons, dev.category, icons.speakers)
            name = dev.title
            if len(name) > self.config.max_device_chars:
                name = name[: self.config.max_device_chars - 1].rstrip() + "…"
            level = self.config.labels.muted if muted else f"{round(vol * 100)}%"

        values = {"{icon}": icon, "{device}": name, "{level}": level}
        for idx, part in enumerate(parts):
            if idx >= len(widgets):
                break
            text = re.sub(r"<span.*?>|</span>", "", part).strip() if "<span" in part else part.strip()
            for k, v in values.items():
                text = text.replace(k, v)
            label: QLabel = widgets[idx]
            label.setText(text)
            base = (label.property("class") or "").replace(" muted", "")
            label.setProperty("class", f"{base} muted" if muted else base)
            refresh_widget_style(label)

        if self.config.tooltip:
            tip = dev.friendly_name if dev else self.config.labels.no_device
            set_tooltip(self, f"{tip} · {level}")

    # ---------------------------------------------------------------- menu

    def _toggle_menu(self) -> None:
        if self.dialog is not None and is_valid_qobject(self.dialog) and self.dialog.isVisible():
            self.dialog.hide()
            return
        self._show_menu()

    def _show_menu(self) -> None:
        m = self.config.menu
        self.dialog = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        self.dialog.setProperty("class", "audio-orbit-menu")

        layout = QVBoxLayout(self.dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas = OrbitCanvas(
            self.dialog,
            width=m.width,
            height=m.height,
            colors=self._colors(),
            icons=self.config.icons.model_dump(),
            labels=self.config.labels.model_dump(),
            font_family=m.font_family,
            show_settings_node=m.show_settings_node,
            animate_orbit=m.animate_orbit,
            show_input_tab=m.show_input_tab and self._in is not None,
        )
        self.canvas.device_selected.connect(self._on_device_selected)
        self.canvas.mode_changed.connect(self._on_mode_changed)
        self.canvas.mute_toggled.connect(self._on_mute_toggled)
        self.canvas.volume_step.connect(lambda d: self._step_volume(self._mode, d))
        self.canvas.volume_set.connect(lambda v: self._set_volume(self._mode, v))
        self.canvas.settings_requested.connect(self._open_settings)
        layout.addWidget(self.canvas)

        self._mode = "output"
        self._refresh_canvas(animate=True)

        self.dialog.adjustSize()
        self.dialog.setPosition(
            alignment=m.alignment,
            direction=m.direction,
            offset_left=m.offset_left,
            offset_top=m.offset_top,
        )
        self.dialog.show()

    def _refresh_canvas(self, animate: bool = False) -> None:
        if not self._canvas_alive():
            return
        svc = self._service(self._mode)
        vol, muted = self._read_volume(self._mode)
        self.canvas.set_state(
            self._devices(self._mode),
            svc.get_default_device_id(),
            vol,
            muted,
            mode=self._mode,
            animate=animate,
        )

    # ------------------------------------------------------------- actions

    def _on_device_selected(self, device_id: str) -> None:
        if self._switching:
            return
        roles = [ERole.eConsole, ERole.eMultimedia]
        if self.config.switch_communications:
            roles.append(ERole.eCommunications)

        # Animate immediately; Windows does the actual switch on a worker thread
        # (SetDefaultDevice can block for a few hundred ms, which froze the UI).
        if self._canvas_alive():
            vol, muted = self._read_volume(self._mode)
            self.canvas.set_state(self.canvas.devices, device_id, vol, muted, mode=self._mode)
        self._switching = True

        def worker() -> None:
            ok = True
            comtypes.CoInitialize()
            try:
                AudioUtilities.SetDefaultDevice(device_id, roles=roles)
            except Exception as e:
                logging.error("AudioOrbit: failed to switch device: %s", e)
                ok = False
            finally:
                comtypes.CoUninitialize()
            self._switch_done.emit(device_id, ok)

        threading.Thread(target=worker, name="AudioOrbitSwitch", daemon=True).start()

        if self.config.menu.close_on_select and self.dialog and is_valid_qobject(self.dialog):
            self.dialog.hide()

    def _on_switch_done(self, _device_id: str, ok: bool) -> None:
        self._switching = False
        # On failure this snaps the panel back to the real default device.
        self._device_timer.start()
        if not ok:
            self._refresh_canvas()

    def _on_mode_changed(self, mode: str) -> None:
        self._mode = mode
        self._refresh_canvas(animate=True)

    def _on_mute_toggled(self) -> None:
        self._toggle_mute(self._mode)

    def _toggle_output_mute(self) -> None:
        self._toggle_mute("output")

    def _toggle_mute(self, mode: str) -> None:
        iface = self._volume_iface(mode)
        if iface is None:
            return
        try:
            iface.SetMute(not bool(iface.GetMute()), None)
        except Exception as e:
            logging.error("AudioOrbit: failed to toggle mute: %s", e)
            return
        if mode == "output":
            self._update_label()
        if self._canvas_alive() and self._mode == mode:
            self.canvas.set_volume(*self._read_volume(mode))

    def _step_volume(self, mode: str, direction: int) -> None:
        iface = self._volume_iface(mode)
        if iface is None:
            return
        try:
            current = float(iface.GetMasterVolumeLevelScalar())
            new = max(0.0, min(1.0, current + direction * self.config.scroll_step / 100))
            iface.SetMasterVolumeLevelScalar(new, None)
        except Exception as e:
            logging.error("AudioOrbit: failed to change volume: %s", e)
            return
        if self._canvas_alive() and self._mode == mode:
            self.canvas.set_volume(*self._read_volume(mode))
        if mode == "output":
            self._update_label()

    def _set_volume(self, mode: str, value: float) -> None:
        """Absolute volume from the slider / ring drag."""
        iface = self._volume_iface(mode)
        if iface is None:
            return
        try:
            iface.SetMasterVolumeLevelScalar(max(0.0, min(1.0, value)), None)
        except Exception as e:
            logging.error("AudioOrbit: failed to set volume: %s", e)

    def _open_settings(self) -> None:
        try:
            os.startfile("ms-settings:sound")
        except Exception as e:
            logging.error("AudioOrbit: failed to open sound settings: %s", e)
        if self.dialog and is_valid_qobject(self.dialog):
            self.dialog.hide()

    def wheelEvent(self, a0) -> None:  # noqa: N802
        """Scroll on the bar item changes output volume."""
        if a0 is None:
            return
        delta = a0.angleDelta().y()
        if delta:
            self._step_volume("output", 1 if delta > 0 else -1)
