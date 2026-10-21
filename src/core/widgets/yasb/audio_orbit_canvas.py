"""
Radial "orbit" canvas used by the AudioOrbit widget.

Pure PyQt6 drawing code with no Windows / pycaw dependency, so it can be
previewed on any platform. The widget feeds it a device list and reacts to
its signals.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import QWidget

# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

DEFAULT_COLORS: dict[str, str] = {
    "background": "#121a19",  # #RRGGBB or #AARRGGBB
    "border": "#2a3836",
    "accent": "#7dd9c7",
    "on_accent": "#0f1716",
    "card": "#141d1c",
    "card_hover": "#1b2826",
    "text": "#e6eceb",
    "subtext": "#7f908d",
    "muted": "#55615f",
    "danger": "#e78a8a",
}

DEFAULT_ICONS: dict[str, str] = {
    "headphones": "\uf025",
    "speakers": "\uf028",
    "monitor": "\uf108",
    "bluetooth": "\uf293",
    "microphone": "\uf130",
    "settings": "\uf013",
    "muted": "\ueee8",
    "mic_muted": "\uf131",
    "check": "\uf00c",
    "unmuted": "\uf028",
    "output_tab": "\uf028",
    "input_tab": "\uf130",
}

DEFAULT_LABELS: dict[str, str] = {
    "output": "Ieșire",
    "input": "Intrare",
    "active": "Activ",
    "muted": "Mut",
    "settings_title": "Setări sunet",
    "settings_sub": "Panoul Windows",
    "empty_title": "Niciun alt dispozitiv",
    "empty_sub": "Conectează căști sau boxe",
    "empty_sub_input": "Conectează un microfon",
    "switch_hint": "Click pentru a comuta",
    "set_badge": "SETAT",
    "switched_badge": "COMUTAT",
    "muted_badge": "MUT",
}

_HEADPHONE_RE = re.compile(
    r"head(phone|set)|căști|casti|earbud|buds|airpods|tune|wh-|wf-|bose|jbl|sony|hands-free|handsfree",
    re.I,
)
_MONITOR_RE = re.compile(r"hdmi|displayport|display|monitor|nvidia|amd high definition|intel.*display|tv\b", re.I)
_BT_RE = re.compile(r"bluetooth|\bbt\b", re.I)
_DRIVER_RE = re.compile(r"audio|high definition|realtek|nvidia|amd|intel|\bsst\b|usb", re.I)
_GENERIC_RE = re.compile(
    r"^(speakers?|headphones?|headset|difuzoare|căști|casti|digital output|realtek digital output|"
    r"microphone|microfon|line|stereo mix|earphones?)$",
    re.I,
)
_MIC_RE = re.compile(r"micro|mic\b|line in|array", re.I)


@dataclass
class OrbitDevice:
    id: str
    friendly_name: str
    title: str = ""
    kind: str = ""
    category: str = "speakers"

    @classmethod
    def from_friendly(cls, device_id: str, friendly: str | None, is_input: bool = False) -> OrbitDevice:
        friendly = friendly or "Dispozitiv necunoscut"
        # Windows names look like "Headphones (JBL Tune 720BT)" / "Difuzoare (Realtek(R) Audio)"
        m = re.match(r"^\s*(.+?)\s*\((.+)\)\s*$", friendly)
        if m:
            kind, title = m.group(1), m.group(2)
            # "LG ULTRAGEAR (NVIDIA High Definition Audio)": the useful name is outside
            if _DRIVER_RE.search(title) and not _GENERIC_RE.search(kind):
                kind, title = title, kind
        else:
            kind, title = ("", friendly)
        if is_input:
            category = "microphone"
        elif _HEADPHONE_RE.search(friendly):
            category = "headphones"
        elif _MONITOR_RE.search(friendly):
            category = "monitor"
        elif _BT_RE.search(friendly):
            category = "bluetooth"
        elif _MIC_RE.search(friendly):
            category = "microphone"
        else:
            category = "speakers"
        return cls(id=device_id, friendly_name=friendly, title=title, kind=kind, category=category)


@dataclass
class _Node:
    key: str  # device id, or "__settings__" / "__empty__"
    title: str
    subtitle: str
    icon: str
    angle: float
    rect: QRectF = field(default_factory=QRectF)
    interactive: bool = True
    title_el: str = ""
    subtitle_el: str = ""
    active: bool = False


# --------------------------------------------------------------------------- #
# Canvas (minimal)
# --------------------------------------------------------------------------- #
#
#   chips on a faint orbit  ·  small core with the level  ·  thin volume ring
#   thin slider row  ·  footer: Iesire | Intrare  ............  [gear] [mute]
#
# Performance: the panel + orbit and the resting chips are cached pixmaps;
# volume changes repaint only the core and the slider row, hover only the
# chip involved. Colors can be swapped live with set_colors() (wallpaper
# palette), which just drops the caches.


class OrbitCanvas(QWidget):
    device_selected = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    mute_toggled = pyqtSignal()
    volume_step = pyqtSignal(int)
    settings_requested = pyqtSignal()
    volume_set = pyqtSignal(float)

    def __init__(
        self,
        parent: QWidget | None = None,
        width: int = 520,
        height: int = 480,
        colors: dict[str, str] | None = None,
        icons: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
        font_family: str = "JetBrainsMono NF",
        show_settings_node: bool = True,
        animate_orbit: bool = False,  # kept for config compatibility
        show_input_tab: bool = True,
    ):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.icons = {**DEFAULT_ICONS, **(icons or {})}
        self.labels = {**DEFAULT_LABELS, **(labels or {})}
        self.font_family = font_family
        self.show_settings = show_settings_node
        self.show_input_tab = show_input_tab
        self.c: dict[str, QColor] = {}
        self.set_colors(colors or {}, repaint=False)

        self.mode = "output"
        self.devices: list[OrbitDevice] = []
        self.active_id: str | None = None
        self.volume = 0.0
        self.muted = False

        self._nodes: list[_Node] = []
        self._hover: str | None = None
        self._drag: str | None = None  # "slider" | "ring"
        self._ignore_clicks_until = 0.0
        self._tab_rects: dict[str, QRectF] = {}
        self._gear_rect = QRectF()
        self._mute_rect = QRectF()

        self._footer_h = 44.0
        self._slider_h = 44.0
        self._core_r = 58.0
        self._ring_r = 74.0

        self._fonts: dict[tuple[int, int], QFont] = {}
        self._bg_cache: QPixmap | None = None
        self._nodes_cache: QPixmap | None = None

        self._intro = 1.0
        self._pulse = 0.0
        self._intro_anim = QVariantAnimation(self, duration=300, startValue=0.0, endValue=1.0)
        self._intro_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._intro_anim.valueChanged.connect(self._set_intro)
        self._intro_anim.finished.connect(self._intro_done)
        self._pulse_anim = QVariantAnimation(self, duration=280, startValue=0.0, endValue=1.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pulse_anim.valueChanged.connect(self._set_pulse)

    # ------------------------------------------------------------------ API
    def set_colors(self, colors: dict[str, str], repaint: bool = True) -> None:
        merged = {**DEFAULT_COLORS, **{k: v for k, v in colors.items() if v}}
        self.c = {k: QColor(v) for k, v in merged.items()}
        self._bg_cache = None
        self._nodes_cache = None
        if repaint:
            self.update()

    def set_state(self, devices, active_id, volume, muted, mode=None, animate=False) -> None:
        switched = active_id != self.active_id and self.active_id is not None
        mode_changed = mode is not None and mode != self.mode
        if not mode_changed and {d.id for d in devices} == {d.id for d in self.devices}:
            order = {d.id: i for i, d in enumerate(self.devices)}
            devices = sorted(devices, key=lambda d: order[d.id])
        same_devices = not mode_changed and [d.id for d in devices] == [d.id for d in self.devices]
        if mode is not None:
            self.mode = mode
        self.devices = devices
        self.active_id = active_id
        if self._drag is None:
            self.volume = max(0.0, min(1.0, volume))
        mute_changed = muted != self.muted
        self.muted = muted

        if same_devices and not switched and not animate:
            if mute_changed:
                self._nodes_cache = None
                self.update()
            else:
                self._update_volume_regions()
            return
        if not same_devices or animate:
            self._layout_nodes()
            self.play_intro()
        self._nodes_cache = None
        if switched:
            self._ignore_clicks_until = time.monotonic() + 0.55
        if switched or animate or mode_changed:
            self._pulse_anim.stop()
            self._pulse_anim.start()
        self.update()

    def set_volume(self, volume: float, muted: bool) -> None:
        if self._drag is not None:
            volume = self.volume
        volume = max(0.0, min(1.0, volume))
        if muted != self.muted:
            self.muted, self.volume = muted, volume
            self._nodes_cache = None
            self.update()
            return
        if abs(volume - self.volume) < 1e-4:
            return
        self.volume = volume
        self._update_volume_regions()

    def play_intro(self) -> None:
        self._intro_anim.stop()
        self._intro = 0.0
        self._intro_anim.start()

    def stop_animations(self) -> None:
        self._intro_anim.stop()
        self._pulse_anim.stop()

    # ------------------------------------------------------------ geometry
    def _orbit_h(self) -> float:
        return self.height() - self._footer_h - self._slider_h

    def _center(self) -> QPointF:
        return QPointF(self.width() / 2, self._orbit_h() / 2)

    def _radii(self) -> tuple[float, float]:
        return min(self.width() / 2 - 70, 190.0), min(self._orbit_h() / 2 - 54, 142.0)

    def _core_bounds(self):
        c = self._center()
        r = self._ring_r + 12
        return QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r).toAlignedRect()

    def _slider_bounds(self):
        return QRectF(0, self._orbit_h(), self.width(), self._slider_h).toAlignedRect()

    def _footer_bounds(self):
        return QRectF(0, self.height() - self._footer_h, self.width(), self._footer_h).toAlignedRect()

    def _track(self) -> QRectF:
        cy = self._orbit_h() + self._slider_h / 2
        return QRectF(50.0, cy - 2, self.width() - 50.0 - 70.0, 4.0)

    def _update_volume_regions(self) -> None:
        self.update(self._core_bounds())
        self.update(self._slider_bounds())

    def _font(self, size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        key = (int(size * 10), int(weight.value))
        f = self._fonts.get(key)
        if f is None:
            f = QFont(self.font_family)
            f.setPixelSize(int(size))
            f.setWeight(weight)
            self._fonts[key] = f
        return f

    def _fill(self) -> QColor:
        return QColor(self.c["muted"] if self.muted else self.c["accent"])

    def _alpha(self, color: QColor, a: float) -> QColor:
        col = QColor(color)
        col.setAlphaF(max(0.0, min(1.0, a)))
        return col

    def _active_device(self) -> OrbitDevice | None:
        return next((d for d in self.devices if d.id == self.active_id), None)

    def _layout_nodes(self) -> None:
        counts: dict[str, int] = {}
        for d in self.devices:
            counts[d.title] = counts.get(d.title, 0) + 1
        fm = QFontMetrics(self._font(11.5, QFont.Weight.DemiBold))
        rx, ry = self._radii()
        c = self._center()
        n = max(len(self.devices), 1)
        nodes: list[_Node] = []
        for i, d in enumerate(self.devices):
            # two devices called "Realtek(R) Audio" show their type instead
            label = d.kind if counts[d.title] > 1 and d.kind else d.title
            a = math.radians(-90 + i * 360 / n)
            w = max(96.0, min(196.0, fm.horizontalAdvance(label) + 50.0))
            h = 32.0
            px = c.x() + rx * math.cos(a) + math.cos(a) * w * 0.22
            py = c.y() + ry * math.sin(a)
            x = min(max(px - w / 2, 12.0), self.width() - w - 12)
            y = min(max(py - h / 2, 12.0), self._orbit_h() - h - 6)
            node = _Node(
                key=d.id,
                title=d.title,
                subtitle=d.kind,
                icon=self.icons.get(d.category, self.icons["speakers"]),
                angle=a,
                rect=QRectF(x, y, w, h),
            )
            node.title_el = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(w - 46))
            nodes.append(node)
        self._separate(nodes)
        self._nodes = nodes

    def _separate(self, nodes: list[_Node]) -> None:
        top, bottom = 12.0, self._orbit_h() - 6
        for _ in range(40):
            moved = False
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    a, b = nodes[i].rect, nodes[j].rect
                    if not a.adjusted(-6, -6, 6, 6).intersects(b):
                        continue
                    up, lo = (a, b) if a.center().y() <= b.center().y() else (b, a)
                    ov = up.bottom() + 6 - lo.top()
                    if ov <= 0:
                        continue
                    up.translate(0, -ov / 2)
                    lo.translate(0, ov / 2)
                    for r in (up, lo):
                        if r.top() < top:
                            r.translate(0, top - r.top())
                        if r.bottom() > bottom:
                            r.translate(0, bottom - r.bottom())
                    moved = True
            if not moved:
                break

    # ----------------------------------------------------------- animation
    def _set_intro(self, v) -> None:
        self._intro = float(v)
        self.update(QRectF(0, 0, self.width(), self._orbit_h()).toAlignedRect())

    def _intro_done(self) -> None:
        self._intro = 1.0
        self.update()

    def _set_pulse(self, v) -> None:
        self._pulse = math.sin(math.pi * float(v))
        self.update(self._core_bounds())

    def _node_rect_now(self, node: _Node) -> QRectF:
        t, c = self._intro, self._center()
        r = QRectF(node.rect)
        r.moveCenter(
            QPointF(c.x() + (node.rect.center().x() - c.x()) * t, c.y() + (node.rect.center().y() - c.y()) * t)
        )
        return r

    # --------------------------------------------------------------- caches
    def _pixmap(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        return pm

    def _bg(self) -> QPixmap:
        if self._bg_cache is None:
            pm = self._pixmap()
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(r, 14, 14)
            p.fillPath(path, self.c["background"])
            p.setPen(QPen(self.c["border"], 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            rx, ry = self._radii()
            pen = QPen(self._alpha(self.c["accent"], 0.18), 1)
            pen.setDashPattern([3, 4])
            p.setPen(pen)
            p.drawEllipse(self._center(), rx, ry)
            p.end()
            self._bg_cache = pm
        return self._bg_cache

    def _chips(self) -> QPixmap:
        if self._nodes_cache is None:
            pm = self._pixmap()
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            for node in self._nodes:
                self._paint_chip(p, node, node.rect, hovered=False)
            p.end()
            self._nodes_cache = pm
        return self._nodes_cache

    # ---------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:  # noqa: N802
        clip = QRectF(event.rect())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.drawPixmap(0, 0, self._bg())
        if self._intro >= 1.0 and self._intro_anim.state() != QVariantAnimation.State.Running:
            p.drawPixmap(0, 0, self._chips())
            hov = next((n for n in self._nodes if n.key == self._hover and n.key != self.active_id), None)
            if hov is not None and clip.intersects(hov.rect):
                self._paint_chip(p, hov, hov.rect, hovered=True)
        else:
            p.save()
            p.setOpacity(max(0.0, self._intro))
            for node in self._nodes:
                self._paint_chip(p, node, self._node_rect_now(node), hovered=False)
            p.restore()
        if clip.intersects(QRectF(self._core_bounds())):
            self._paint_core(p)
        if clip.intersects(QRectF(self._slider_bounds())):
            self._paint_slider(p)
        if clip.intersects(QRectF(self._footer_bounds())):
            self._paint_footer(p)
        p.end()

    def _icon_for(self, dev: OrbitDevice | None) -> str:
        if self.muted:
            return self.icons["mic_muted" if self.mode == "input" else "muted"]
        if dev is None:
            return self.icons["microphone" if self.mode == "input" else "speakers"]
        return self.icons.get(dev.category, self.icons["speakers"])

    def _paint_chip(self, p: QPainter, node: _Node, r: QRectF, hovered: bool) -> None:
        active = node.key == self.active_id
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        if active:
            p.fillPath(path, self._fill())
            fg = self.c["on_accent"]
        else:
            p.fillPath(path, self.c["card_hover"] if hovered else self.c["card"])
            p.setPen(QPen(self.c["accent"] if hovered else self._alpha(self.c["border"], 0.9), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            fg = self.c["text"]
        f_icon, f_txt = self._font(13), self._font(11.5, QFont.Weight.DemiBold)
        icon_w = QFontMetrics(f_icon).horizontalAdvance(node.icon)
        txt_w = QFontMetrics(f_txt).horizontalAdvance(node.title_el)
        x = r.center().x() - (icon_w + 8 + txt_w) / 2
        p.setPen(fg)
        p.setFont(f_icon)
        p.drawText(QRectF(x, r.y(), icon_w + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, node.icon)
        p.setFont(f_txt)
        p.drawText(QRectF(x + icon_w + 8, r.y(), txt_w + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, node.title_el)

    def _paint_core(self, p: QPainter) -> None:
        c = self._center()
        fill = self._fill()
        ring_active = self._drag == "ring" or self._hover == "ring"
        rect = QRectF(c.x() - self._ring_r, c.y() - self._ring_r, 2 * self._ring_r, 2 * self._ring_r)
        w = 5 if ring_active else 3
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._alpha(fill, 0.2), w))
        p.drawEllipse(rect)
        if self.volume > 0:
            p.setPen(QPen(fill, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 90 * 16, int(-self.volume * 360 * 16))
        a = math.radians(90 - self.volume * 360)
        knob = QPointF(c.x() + self._ring_r * math.cos(a), c.y() - self._ring_r * math.sin(a))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.c["text"])
        kr = 6.5 if ring_active else 5.0
        p.drawEllipse(knob, kr, kr)

        r = self._core_r * (1 + 0.05 * self._pulse)
        p.setBrush(fill)
        p.drawEllipse(c, r, r)
        p.setPen(self.c["on_accent"])
        p.setFont(self._font(26))
        p.drawText(
            QRectF(c.x() - r, c.y() - 30, 2 * r, 32),
            Qt.AlignmentFlag.AlignCenter,
            self._icon_for(self._active_device()),
        )
        p.setFont(self._font(15, QFont.Weight.Bold))
        value = self.labels["muted"] if self.muted else f"{round(self.volume * 100)}%"
        p.drawText(QRectF(c.x() - r, c.y() + 4, 2 * r, 22), Qt.AlignmentFlag.AlignCenter, value)

    def _paint_slider(self, p: QPainter) -> None:
        t = self._track()
        cy = t.center().y()
        p.setPen(self.c["muted"] if self.muted else self.c["subtext"])
        p.setFont(self._font(14))
        p.drawText(QRectF(18, cy - 12, 24, 24), Qt.AlignmentFlag.AlignCenter, self._icon_for(None))
        tp = QPainterPath()
        tp.addRoundedRect(t, 2, 2)
        p.fillPath(tp, self._alpha(self.c["border"], 1.0))
        fw = t.width() * self.volume
        if fw > 0.5:
            fp = QPainterPath()
            fp.addRoundedRect(QRectF(t.left(), t.top(), max(fw, 4), t.height()), 2, 2)
            p.fillPath(fp, self._fill())
        active = self._drag == "slider" or self._hover == "slider"
        kr = 7.0 if active else 6.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.c["text"])
        p.drawEllipse(QPointF(min(max(t.left() + fw, t.left() + kr), t.right() - kr), cy), kr, kr)
        p.setPen(self.c["subtext"])
        p.setFont(self._font(12, QFont.Weight.DemiBold))
        value = self.labels["muted"] if self.muted else f"{round(self.volume * 100)}%"
        p.drawText(
            QRectF(t.right() + 8, cy - 12, self.width() - t.right() - 26, 24),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            value,
        )

    def _paint_footer(self, p: QPainter) -> None:
        top = self.height() - self._footer_h
        cy = top + (self._footer_h - 8) / 2
        tabs = [("output", self.labels["output"])]
        if self.show_input_tab:
            tabs.append(("input", self.labels["input"]))
        f = self._font(11.5, QFont.Weight.DemiBold)
        fm = QFontMetrics(f)
        x = 14.0
        self._tab_rects = {}
        p.setFont(f)
        for key, label in tabs:
            w = fm.horizontalAdvance(label) + 24
            r = QRectF(x, cy - 14, w, 28)
            self._tab_rects[key] = r
            on = self.mode == key
            if on or self._hover == f"tab:{key}":
                bp = QPainterPath()
                bp.addRoundedRect(r, 7, 7)
                p.fillPath(bp, self.c["card_hover"])
            p.setPen(self.c["accent"] if on else (self.c["text"] if self._hover == f"tab:{key}" else self.c["subtext"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
            x += w + 4

        self._mute_rect = QRectF(self.width() - 14 - 32, cy - 16, 32, 32)
        self._gear_rect = QRectF(self._mute_rect.left() - 6 - 32, cy - 16, 32, 32) if self.show_settings else QRectF()
        for key, rect, glyph in (
            ("settings", self._gear_rect, self.icons["settings"]),
            ("mute", self._mute_rect, self._icon_for(None) if self.muted else self.icons["unmuted"]),
        ):
            if rect.isNull():
                continue
            bp = QPainterPath()
            bp.addRoundedRect(rect, 8, 8)
            if key == "mute" and self.muted:
                p.fillPath(bp, self.c["danger"])
                p.setPen(self.c["on_accent"])
            else:
                if self._hover == key:
                    p.fillPath(bp, self.c["card_hover"])
                p.setPen(self.c["text"] if self._hover == key else self.c["subtext"])
            p.setFont(self._font(15))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)

    # ---------------------------------------------------------------- input
    def _hit(self, pos: QPointF) -> str | None:
        for node in self._nodes:
            if node.rect.contains(pos):
                return node.key
        for key, r in self._tab_rects.items():
            if r.contains(pos):
                return f"tab:{key}"
        if self._mute_rect.contains(pos):
            return "mute"
        if not self._gear_rect.isNull() and self._gear_rect.contains(pos):
            return "settings"
        if self._track().adjusted(-10, -12, 10, 12).contains(pos):
            return "slider"
        c = self._center()
        d = math.hypot(pos.x() - c.x(), pos.y() - c.y())
        if self._core_r + 6 <= d <= self._ring_r + 14:
            return "ring"
        return None

    def _region_for(self, key: str | None):
        if key is None:
            return None
        if key == "ring":
            return self._core_bounds()
        if key == "slider":
            return self._slider_bounds()
        if key in ("mute", "settings") or key.startswith("tab:"):
            return self._footer_bounds()
        node = next((n for n in self._nodes if n.key == key), None)
        return node.rect.adjusted(-2, -2, 2, 2).toAlignedRect() if node else None

    def _drag_to(self, pos: QPointF) -> None:
        if self._drag == "slider":
            t = self._track()
            v = (pos.x() - t.left()) / t.width()
        else:
            c = self._center()
            v = (math.atan2(pos.x() - c.x(), -(pos.y() - c.y())) % (2 * math.pi)) / (2 * math.pi)
            if self.volume > 0.8 and v < 0.2:
                v = 1.0
            elif self.volume < 0.2 and v > 0.8:
                v = 0.0
        v = max(0.0, min(1.0, v))
        if v != self.volume and (abs(v - self.volume) >= 0.004 or v in (0.0, 1.0)):
            self.volume = v
            self.volume_set.emit(v)
            self._update_volume_regions()

    def mousePressEvent(self, e: QMouseEvent | None) -> None:  # noqa: N802
        if e is None or e.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(e.position())
        if hit in ("slider", "ring"):
            self._drag = hit
            self._drag_to(e.position())
            self._update_volume_regions()

    def mouseMoveEvent(self, e: QMouseEvent | None) -> None:  # noqa: N802
        if e is None:
            return
        if self._drag is not None:
            self._drag_to(e.position())
            return
        hit = self._hit(e.position())
        if hit == self.active_id:
            hit = None  # the active chip is not clickable
        if hit != self._hover:
            old = self._region_for(self._hover)
            self._hover = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            for region in (old, self._region_for(hit)):
                if region is not None:
                    self.update(region)

    def leaveEvent(self, _e) -> None:  # noqa: N802
        if self._hover is not None:
            region = self._region_for(self._hover)
            self._hover = None
            if region is not None:
                self.update(region)

    def mouseReleaseEvent(self, e: QMouseEvent | None) -> None:  # noqa: N802
        if e is None or e.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag is not None:
            self._drag = None
            self._update_volume_regions()
            return
        hit = self._hit(e.position())
        if hit is None or hit in ("slider", "ring"):
            return
        if hit == "mute":
            self.mute_toggled.emit()
        elif hit == "settings":
            self.settings_requested.emit()
        elif hit.startswith("tab:"):
            mode = hit.split(":", 1)[1]
            if mode != self.mode:
                self.mode_changed.emit(mode)
        elif hit != self.active_id and time.monotonic() >= self._ignore_clicks_until:
            self._ignore_clicks_until = time.monotonic() + 0.55
            self.device_selected.emit(hit)

    def wheelEvent(self, e: QWheelEvent | None) -> None:  # noqa: N802
        if e is None:
            return
        delta = e.angleDelta().y()
        if delta:
            self.volume_step.emit(1 if delta > 0 else -1)
        e.accept()
