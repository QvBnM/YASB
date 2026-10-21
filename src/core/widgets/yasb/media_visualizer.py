"""
Media visualizer: YASB's audio visualizer, shown only while a media session is playing.

The stock visualizer draws whatever goes out of the speakers, so a Wallpaper Engine
wallpaper with sound, a game or a notification also made it move. This one listens to
Windows' media sessions (the same source the media widget uses) and stays collapsed
unless one of them is actually playing.
"""

import logging

from core.validation.widgets.yasb.media_visualizer import MediaVisualizerConfig
from core.widgets.services.media.media import WindowsMedia
from core.widgets.yasb.audio_visualizer import AudioVisualizerWidget


class MediaVisualizerWidget(AudioVisualizerWidget):
    validation_schema = MediaVisualizerConfig

    def __init__(self, config: MediaVisualizerConfig) -> None:
        self._media_playing = not config.only_when_media_playing
        super().__init__(config)
        if not config.only_when_media_playing:
            return
        self._media = WindowsMedia()
        for signal in (
            self._media.playback_info_changed,
            self._media.current_session_changed,
            self._media.media_properties_changed,
        ):
            signal.connect(self._sync_media)
        if not self._is_media_playing():
            self._collapse_now(animate=False)

    # ------------------------------------------------------------------ media state
    def _is_media_playing(self) -> bool:
        try:
            trackers = getattr(self._media, "_trackers", {})
            return any(state.is_playing for state in list(trackers.values()))
        except Exception as e:
            logging.debug("media visualizer: cannot read media state: %s", e)
            return True  # fail open: behave like the normal visualizer

    def _sync_media(self, *_args) -> None:
        playing = self._is_media_playing()
        if playing == self._media_playing:
            return
        self._media_playing = playing
        if playing:
            if self._idle_hidden and self._service.is_active:
                self._idle_hidden = False
                self._apply_collapsed(False)
        else:
            self._collapse_now(animate=True)

    def _collapse_now(self, animate: bool) -> None:
        self._media_playing = False
        if self._idle_hidden:
            return
        self._fade_timer.stop()
        self._reset_visual()
        self._idle_hidden = True
        self._apply_collapsed(True, animate=animate)

    # ------------------------------------------------------------------ gates
    def _on_audio_started(self) -> None:
        if self._media_playing:
            super()._on_audio_started()

    def _on_frame(self) -> None:
        if self._media_playing:
            super()._on_frame()
