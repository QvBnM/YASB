"""
AudioSlider widget: a compact volume slider that lives directly in the bar.

[speaker icon] [=====o-----] 75%

* drag the slider to change the default output volume
* click the speaker to mute / unmute
* scroll anywhere on the widget to step the volume
"""

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QPushButton, QSlider

from core.utils.utilities import refresh_widget_style
from core.validation.widgets.yasb.audio_slider import AudioSliderConfig
from core.widgets.base import BaseWidget
from core.widgets.services.volume.service import AudioOutputService


class AudioSliderWidget(BaseWidget):
    validation_schema = AudioSliderConfig

    def __init__(self, config: AudioSliderConfig):
        super().__init__(class_name=f"audio-slider-widget {config.class_name}")
        self.config = config
        self._updating = False  # True while we move the slider from code

        self._init_container()

        self._icon = QPushButton()
        self._icon.setProperty("class", "icon")
        self._icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon.setFlat(True)
        self._icon.clicked.connect(self._toggle_mute)
        self._icon.setVisible(self.config.show_icon)
        self._widget_container_layout.addWidget(self._icon)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setProperty("class", "volume-slider")
        self._slider.setRange(0, 100)
        self._slider.setFixedWidth(self.config.slider_width)
        self._slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._widget_container_layout.addWidget(self._slider)

        self._value = QLabel()
        self._value.setProperty("class", "label")
        self._value.setVisible(self.config.show_value)
        self._widget_container_layout.addWidget(self._value)

        self.register_callback("toggle_mute", self._toggle_mute)
        self.callback_left = self.config.callbacks.on_left
        self.callback_right = self.config.callbacks.on_right
        self.callback_middle = self.config.callbacks.on_middle

        # Windows sends a burst of notifications while the volume moves: coalesce them
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(30)
        self._refresh_timer.timeout.connect(self._refresh)

        self._service = AudioOutputService()
        self._service.register_widget(self)
        self.destroyed.connect(self._unregister)
        self._refresh()

    def _unregister(self) -> None:
        try:
            self._service.unregister_widget(self)
        except Exception:
            pass

    # ------------------------------------------------- service listener API
    def on_output_volume_changed(self) -> None:
        self._refresh_timer.start()

    def on_output_device_changed(self) -> None:
        self._refresh_timer.start()

    # ----------------------------------------------------------------- state
    def _iface(self):
        return self._service.get_volume_interface()

    def _read(self) -> tuple[int, bool] | None:
        iface = self._iface()
        if iface is None:
            return None
        try:
            return round(iface.GetMasterVolumeLevelScalar() * 100), bool(iface.GetMute())
        except Exception:
            return None

    def _refresh(self) -> None:
        state = self._read()
        if state is None:
            self._value.setText("—")
            self._slider.setEnabled(False)
            return
        level, muted = state
        self._slider.setEnabled(True)
        if not self._slider.isSliderDown():  # never fight the user's drag
            self._updating = True
            self._slider.setValue(level)
            self._updating = False
        self._value.setText(self.config.muted_text if muted else f"{level}%")
        icons = self.config.icons
        if muted:
            icon = icons.muted
        elif level < 34:
            icon = icons.low
        elif level < 67:
            icon = icons.medium
        else:
            icon = icons.high
        self._icon.setText(icon)
        for w, base in ((self._icon, "icon"), (self._slider, "volume-slider"), (self._value, "label")):
            cls = f"{base} muted" if muted else base
            if w.property("class") != cls:
                w.setProperty("class", cls)
                refresh_widget_style(w)

    # --------------------------------------------------------------- actions
    def _on_slider_changed(self, value: int) -> None:
        if self._updating:
            return
        iface = self._iface()
        if iface is None:
            return
        try:
            iface.SetMasterVolumeLevelScalar(value / 100, None)
        except Exception as e:
            logging.error("AudioSlider: failed to set volume: %s", e)
        self._value.setText(f"{value}%")

    def _toggle_mute(self) -> None:
        iface = self._iface()
        if iface is None:
            return
        try:
            iface.SetMute(not bool(iface.GetMute()), None)
        except Exception as e:
            logging.error("AudioSlider: failed to toggle mute: %s", e)
        self._refresh()

    def wheelEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        delta = a0.angleDelta().y()
        if not delta:
            return
        state = self._read()
        if state is None:
            return
        level = max(0, min(100, state[0] + (self.config.scroll_step if delta > 0 else -self.config.scroll_step)))
        self._slider.setValue(level)  # goes through _on_slider_changed
        a0.accept()
