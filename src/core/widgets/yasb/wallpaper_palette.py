"""
Alegi wallpaper-ul vazand paleta pe care o va da.

Click = galerie: fiecare imagine din folder apare cu culorile barei estimate din ea
(fundal, linie, text secundar, accent, accent 2, text) si cu nota de contrast.
Cand accentul a trebuit corectat ca sa ramana lizibil, scrie cu cat.
Click pe o imagine = o pune ca wallpaper si ruleaza comenzile din `run_after`
(acolo pui yasb_palette.py, care scrie palette.css-ul adevarat).

Estimarea e facuta aici, cu aceeasi regula de contrast; daca generatorul tau alege
altfel culorile, previzualizarea poate diferi putin de rezultat.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import random
import subprocess
import threading

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.utils.utilities import PopupWidget
from core.validation.widgets.yasb.wallpaper_palette import WallpaperPaletteConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb.mint_common import contrast, ensure_contrast, fill_labels, from_hls, mix, rgb_to_hex, to_hls

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPI_GETDESKWALLPAPER = 0x0073
SPI_SETDESKWALLPAPER = 0x0014
CREATE_NO_WINDOW = 0x08000000
CACHE_VERSION = 1


# --------------------------------------------------------------------------- paleta estimata


def estimate_palette(image, min_contrast: float = 4.5) -> dict:
    """Paleta barei estimata dintr-o imagine (PIL.Image)."""
    from PIL import Image

    small = image.convert("RGB").resize((96, 96))
    q = small.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    colors = sorted(
        ((count, rgb_to_hex(pal[i * 3 : i * 3 + 3])) for count, i in (q.getcolors() or [])),
        reverse=True,
    )
    dominant = colors[0][1] if colors else "#1a2a28"
    dh, _dl, ds = to_hls(dominant)

    bar = from_hls(dh, 0.075, min(ds, 0.35) * 0.6)
    line = from_hls(dh, 0.19, min(ds, 0.3) * 0.5)
    text = from_hls(dh, 0.92, 0.12)
    sub = mix(text, bar, 0.45)

    scored = []
    for count, hx in colors:
        h, l, s = to_hls(hx)
        if s >= 0.2 and 0.25 <= l <= 0.88:
            scored.append((count * (s + 0.2), h, hx))
    scored.sort(reverse=True)
    accent_raw = scored[0][2] if scored else from_hls(dh, 0.7, 0.45)
    ah, al, as_ = to_hls(accent_raw)
    accent_raw = from_hls(ah, max(al, 0.6), min(1.0, max(as_, 0.35)))  # ca in paletele de bara: luminos
    accent2_raw = next((hx for _, h, hx in scored[1:] if min(abs(h - ah), 1 - abs(h - ah)) > 0.08), None)
    if accent2_raw is None:
        accent2_raw = from_hls((ah + 0.45) % 1.0, 0.78, 0.45)

    accent, shift = ensure_contrast(accent_raw, bar, min_contrast)
    accent2, _ = ensure_contrast(accent2_raw, bar, min_contrast)
    return {
        "swatches": [bar, line, sub, accent, accent2, text],
        "text_contrast": round(contrast(text, bar), 1),
        "accent_shift": round(shift, 3),
    }


# --------------------------------------------------------------------------- Windows


def current_wallpaper() -> str:
    try:
        buf = ctypes.create_unicode_buffer(520)
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 520, buf, 0)
        return os.path.abspath(buf.value) if buf.value else ""
    except Exception:
        return ""


def same_path(a: str, b: str) -> bool:
    return bool(a) and bool(b) and os.path.normcase(a) == os.path.normcase(b)


def set_wallpaper(path: str) -> bool:
    try:
        return bool(ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, path, 0x01 | 0x02))
    except Exception:
        logging.exception("wallpaper_palette: nu pot seta wallpaper-ul")
        return False


# --------------------------------------------------------------------------- cache


def _cache_dir() -> str:
    try:
        from core.config import get_config_dir

        base = get_config_dir()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".config", "yasb")
    d = os.path.join(base, "mint_wallpapers")
    os.makedirs(d, exist_ok=True)
    return d


class _Cache:
    def __init__(self):
        self.dir = _cache_dir()
        self.file = os.path.join(self.dir, "cache.json")
        self.lock = threading.Lock()
        try:
            with open(self.file, encoding="utf-8") as f:
                data = json.load(f)
            self.items: dict = data.get("items", {}) if data.get("version") == CACHE_VERSION else {}
        except (OSError, ValueError):
            self.items = {}

    def get(self, path: str, mtime: float) -> dict | None:
        item = self.items.get(path)
        if item and item.get("mtime") == mtime and os.path.exists(item.get("thumb", "")):
            return item
        return None

    def put(self, path: str, item: dict) -> None:
        with self.lock:
            self.items[path] = item

    def save(self) -> None:
        with self.lock:
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "items": self.items}, f)
            os.replace(tmp, self.file)


# --------------------------------------------------------------------------- widget


class _Card(QFrame):
    def __init__(self, owner: WallpaperPaletteWidget, path: str):
        super().__init__()
        self.path = path
        self._owner = owner
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("class", "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        w = owner.config.thumb_width
        self.thumb = QLabel()
        self.thumb.setProperty("class", "thumb")
        self.thumb.setFixedSize(w, round(w * 9 / 16))
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.swatches = QFrame()
        self.swatches.setProperty("class", "swatches")
        self.swatches.setFixedHeight(8)
        sw = QHBoxLayout(self.swatches)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.setSpacing(0)
        self._sw: list[QFrame] = []
        for _ in range(6):
            f = QFrame()
            sw.addWidget(f)
            self._sw.append(f)
        meta = QFrame()
        meta.setProperty("class", "meta")
        ml = QVBoxLayout(meta)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        self.name = QLabel(os.path.splitext(os.path.basename(path))[0])
        self.name.setProperty("class", "name")
        self.note = QLabel("…")
        self.note.setProperty("class", "note")
        self.note.setWordWrap(True)
        self.state = QLabel(owner.config.active_label)
        self.state.setProperty("class", "state")
        self.state.hide()
        for x in (self.name, self.note, self.state):
            ml.addWidget(x)
        lay.addWidget(self.thumb)
        lay.addWidget(self.swatches)
        lay.addWidget(meta)

    def fill(self, item: dict) -> None:
        pm = QPixmap(item["thumb"])
        if not pm.isNull():
            self.thumb.setPixmap(
                pm.scaled(
                    self.thumb.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        for f, color in zip(self._sw, item["swatches"], strict=False):
            f.setStyleSheet(f"background-color: {color}; border: none;")
        shift = item.get("accent_shift", 0)
        if shift >= 0.03:
            self.note.setText(f"accent ajustat cu {round(shift * 100)}% pentru contrast")
            self.note.setProperty("class", "note adjusted")
        else:
            self.note.setText(f"contrast text {item['text_contrast']}:1")
            self.note.setProperty("class", "note")
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)

    def set_active(self, active: bool) -> None:
        self.setProperty("class", "card active" if active else "card")
        self.state.setVisible(active)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._owner.apply(self.path)


class WallpaperPaletteWidget(BaseWidget):
    validation_schema = WallpaperPaletteConfig
    _item_ready = pyqtSignal(str, dict)

    def __init__(self, config: WallpaperPaletteConfig):
        super().__init__(class_name=f"wallpaper-palette-widget {config.class_name}")
        self.config = config
        self._cache = _Cache()
        self._cards: dict[str, _Card] = {}
        self._popup: PopupWidget | None = None
        self._worker: threading.Thread | None = None
        self._complained: set[str] = set()
        self._auto = config.auto_change

        self._init_container()
        self.build_widget_label(config.label)
        fill_labels(self, {})
        self.register_callback("toggle_gallery", self._toggle_gallery)
        self.register_callback("next_wallpaper", self.next_wallpaper)
        self.register_callback("random_wallpaper", self.random_wallpaper)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        self._item_ready.connect(self._on_item)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.next_wallpaper)
        self._set_auto(self._auto)
        QTimer.singleShot(3000, self._precompute)  # galeria se deschide instant si prima data

    # ------------------------------------------------------------------ imagini

    def images(self) -> list[str]:
        roots = self.config.image_path if isinstance(self.config.image_path, list) else [self.config.image_path]
        out: list[str] = []
        for root in roots:
            root = os.path.expandvars(os.path.expanduser(root))
            try:
                for entry in sorted(os.scandir(root), key=lambda e: e.name.lower()):
                    if entry.is_file() and os.path.splitext(entry.name)[1].lower() in IMAGE_EXT:
                        out.append(os.path.abspath(entry.path))
            except FileNotFoundError:
                self._complain(root, "nu exista folderul %s: fie il creezi, fie schimbi image_path")
            except OSError:
                self._complain(root, "nu pot citi folderul %s")
        images = out[: self.config.max_images]
        # Fara nicio imagine, butonul nu are ce deschide: se da la o parte singur (vezi arbitrul).
        visibility.request(self, visibility.SELF, bool(images))
        return images

    def _complain(self, root: str, message: str) -> None:
        """Acelasi folder lipsa nu se scrie in jurnal la fiecare masuratoare, doar o data."""
        if root in self._complained:
            return
        self._complained.add(root)
        logging.warning("wallpaper_palette: " + message, root)

    def _precompute(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        paths = self.images()
        min_c = self.config.min_contrast

        def work():
            from PIL import Image

            dirty = False
            for path in paths:
                try:
                    mtime = os.path.getmtime(path)
                    item = self._cache.get(path, mtime)
                    if item is None:
                        with Image.open(path) as img:
                            img.load()
                            pal = estimate_palette(img, min_c)
                            thumb = img.convert("RGB")
                            thumb.thumbnail((480, 270))
                            name = hashlib.sha1(os.path.normcase(path).encode("utf-8")).hexdigest()[:16] + ".jpg"
                            thumb_path = os.path.join(self._cache.dir, name)
                            thumb.save(thumb_path, "JPEG", quality=85)
                        item = {"mtime": mtime, "thumb": thumb_path, **pal}
                        self._cache.put(path, item)
                        dirty = True
                    self._item_ready.emit(path, item)
                except RuntimeError:
                    return  # widget-ul a fost distrus
                except Exception:
                    logging.debug("wallpaper_palette: %s nu poate fi citit", path, exc_info=True)
            if dirty:
                try:
                    self._cache.save()
                except OSError:
                    logging.warning("wallpaper_palette: nu pot salva cache-ul")

        self._worker = threading.Thread(target=work, name="mint-wallpapers", daemon=True)
        self._worker.start()

    def _on_item(self, path: str, item: dict) -> None:
        card = self._cards.get(path)
        if card is not None:
            try:
                card.fill(item)
            except RuntimeError:
                self._cards.pop(path, None)

    # ------------------------------------------------------------------ galerie

    def _toggle_gallery(self) -> None:
        if self._popup is not None and self._popup.isVisible():
            self._popup.hide_animated()
            return
        m = self.config.menu
        popup = PopupWidget(self, m.blur, m.round_corners, m.round_corners_type, m.border_color)
        popup.setProperty("class", "wallpaper-palette")
        self._popup = popup
        self._cards = {}

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setProperty("class", "header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        title = QLabel(self.config.title)
        title.setProperty("class", "title")
        paths = self.images()
        count = QLabel(f"{len(paths)} imagini")
        count.setProperty("class", "count")
        hl.addWidget(title)
        hl.addStretch(1)
        hl.addWidget(count)
        root.addWidget(header)

        grid_host = QWidget()
        grid_host.setProperty("class", "grid")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        current = current_wallpaper()
        for i, path in enumerate(paths):
            card = _Card(self, path)
            self._cards[path] = card
            card.set_active(same_path(path, current))
            item = self._cache.get(path, os.path.getmtime(path)) if os.path.exists(path) else None
            if item:
                card.fill(item)
            grid.addWidget(card, i // self.config.columns, i % self.config.columns)

        scroll = QScrollArea()
        scroll.setProperty("class", "scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(grid_host)
        grid_host.adjustSize()
        rows = min(self.config.visible_rows, max(1, (len(paths) + self.config.columns - 1) // self.config.columns))
        card_h = round(self.config.thumb_width * 9 / 16) + 8 + 62
        scroll.setFixedHeight(rows * (card_h + 10) + 16)
        scroll.setMinimumWidth(grid_host.sizeHint().width() + 14)
        root.addWidget(scroll)

        footer = QFrame()
        footer.setProperty("class", "footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(0, 0, 0, 0)
        auto_label = QLabel(self.config.auto_label.format(minutes=self.config.auto_change_minutes))
        auto_label.setProperty("class", "footer-label")
        toggle = QPushButton()
        toggle.setCheckable(True)
        toggle.setChecked(self._auto)
        toggle.setProperty("class", "switch")
        toggle.setFixedSize(30, 16)
        toggle.toggled.connect(self._set_auto)
        fl.addWidget(auto_label)
        fl.addStretch(1)
        fl.addWidget(toggle)
        root.addWidget(footer)

        popup.setLayout(root)
        popup.adjustSize()
        popup.setPosition(m.alignment, m.direction, m.offset_left, m.offset_top)
        popup.show()
        self._precompute()

    # ------------------------------------------------------------------ actiuni

    def apply(self, path: str) -> None:
        def work():
            if not set_wallpaper(path):
                return
            for cmd in self.config.run_after:
                try:
                    subprocess.Popen(cmd.replace("{path}", path), shell=True, creationflags=CREATE_NO_WINDOW)
                except Exception:
                    logging.exception("wallpaper_palette: comanda run_after a esuat: %s", cmd)

        threading.Thread(target=work, name="mint-set-wallpaper", daemon=True).start()
        for p, card in list(self._cards.items()):
            try:
                card.set_active(same_path(p, path))
            except RuntimeError:
                self._cards.pop(p, None)

    def next_wallpaper(self) -> None:
        paths = self.images()
        if not paths:
            return
        current = current_wallpaper()
        idx = next((i for i, p in enumerate(paths) if same_path(p, current)), -1)
        self.apply(paths[(idx + 1) % len(paths)])

    def random_wallpaper(self) -> None:
        current = current_wallpaper()
        paths = [p for p in self.images() if not same_path(p, current)]
        if paths:
            self.apply(random.choice(paths))

    def _set_auto(self, on: bool) -> None:
        self._auto = on
        if on:
            self._auto_timer.start(self.config.auto_change_minutes * 60 * 1000)
        else:
            self._auto_timer.stop()
