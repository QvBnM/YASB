"""
Accentul vine din coperta melodiei, cat timp canta.

Widget invizibil. Ia culoarea dominanta (si destul de vie) din coperta, o trece prin
aceeasi regula de contrast ca paleta si o aplica doar pe widget-urile din `targets`
(implicit grupul media si desktop-urile). La pauza revine lin la accentul din palette.css.
"""

from __future__ import annotations

import colorsys
import logging

from PyQt6.QtCore import QTimer, QVariantAnimation
from PyQt6.QtGui import QColor

from core.validation.widgets.yasb.cover_accent import CoverAccentConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb.mint_common import PaletteWatcher, ensure_contrast, find_named, make_invisible, rgb_to_hex

ACCENT_QSS = """
.audio-slider-widget .volume-slider::sub-page {{ background: {c}; border-radius: 2px; }}
.audio-slider-widget .icon:hover, .media-widget .btn:hover, .media-lite-menu .btn:hover {{ color: {c}; }}
.audio-visualizer-widget .audio-visualizer-canvas {{ qproperty-fillbrush: {c}; }}
.windows-desktops .ws-btn.active {{ background-color: {c}; }}
"""


def dominant_color(image, min_saturation: float = 0.18) -> str | None:
    """Culoarea reprezentativa a unei coperte (PIL.Image), sau None daca e prea stearsa."""
    from PIL import Image

    small = image.convert("RGB").resize((48, 48))
    q = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette() or []
    best, best_score = None, -1.0
    for count, idx in q.getcolors() or []:
        r, g, b = palette[idx * 3 : idx * 3 + 3]
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s < min_saturation or l < 0.22 or l > 0.92:
            continue  # fundalurile foarte inchise / albe nu sunt "culoarea" copertei
        # radacina din numarul de pixeli: subiectul viu castiga in fata unui fundal mare si sters
        score = (count**0.5) * (0.2 + s) * (1.2 - abs(l - 0.6))
        if score > best_score:
            best, best_score = (r, g, b), score
    return rgb_to_hex(best) if best else None


class CoverAccentWidget(BaseWidget):
    validation_schema = CoverAccentConfig

    def __init__(self, config: CoverAccentConfig):
        super().__init__(class_name="cover-accent")
        self.config = config
        make_invisible(self)
        self._palette = PaletteWatcher(self, self._on_palette)
        self._shown = ""  # culoarea aplicata acum ("" = paleta)
        self._target = ""
        self._last_key = None
        self._last_color: str | None = None

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(config.transition)
        self._anim.valueChanged.connect(self._on_frame)
        self._anim.finished.connect(self._on_finished)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._evaluate)

        self._media = None
        try:
            from core.widgets.services.media.media import WindowsMedia

            self._media = WindowsMedia()
            for sig in (
                self._media.media_properties_changed,
                self._media.playback_info_changed,
                self._media.current_session_changed,
            ):
                sig.connect(self._debounce.start)
        except Exception:
            logging.warning("cover_accent: serviciul media nu e disponibil")
        QTimer.singleShot(1000, self._evaluate)

    def _on_palette(self, _colors: dict) -> None:
        # wallpaper nou = alt fundal: recalculam contrastul copertei
        self._last_key = None
        self._target = "<palette changed>"
        self._evaluate()

    def _palette_accent(self) -> str:
        return self._palette.colors["accent"]

    def _wanted(self) -> str:
        cs = self._media.current_session if self._media is not None else None
        if cs is None or cs.thumbnail is None or not (cs.is_playing or self.config.keep_on_pause):
            return ""
        key = (cs.app_id, cs.title, cs.artist, id(cs.thumbnail))
        if key != self._last_key:
            self._last_key = key
            try:
                raw = dominant_color(cs.thumbnail, self.config.min_saturation)
            except Exception:
                logging.debug("cover_accent: nu pot citi coperta", exc_info=True)
                raw = None
            self._last_color = (
                ensure_contrast(raw, self._palette.colors["bar"], self.config.min_contrast)[0] if raw else None
            )
        return self._last_color or ""

    def _evaluate(self) -> None:
        target = self._wanted()
        if target == self._target:
            return
        self._target = target
        start = QColor(self._shown or self._palette_accent())
        end = QColor(target or self._palette_accent())
        self._anim.stop()
        if self.config.transition <= 0:
            self._on_frame(end)
            self._on_finished()
            return
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _apply(self, color: str) -> None:
        qss = ACCENT_QSS.format(c=color) if color else ""
        for w in find_named(self.config.targets, self.window()):
            try:
                w.setStyleSheet(qss)
            except RuntimeError:
                pass

    def _on_frame(self, value) -> None:
        if isinstance(value, QColor):
            self._shown = value.name()
            self._apply(self._shown)

    def _on_finished(self) -> None:
        if not self._target:
            # inapoi la paleta: scoatem stilul local, ca sa se aplice din nou styles.css
            self._shown = ""
            self._apply("")
