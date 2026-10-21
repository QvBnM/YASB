from core.validation.widgets.yasb.audio_visualizer import AudioVisualizerConfig


class MediaVisualizerConfig(AudioVisualizerConfig):
    # Show the visualizer only while a media player (Spotify, YouTube in the browser, ...)
    # reports "playing" to Windows. Other sounds (Wallpaper Engine, games, notifications)
    # no longer wake it up.
    only_when_media_playing: bool = True
