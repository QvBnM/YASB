"""
Desktop-urile virtuale spun ce e pe ele.

Extinde widget-ul windows_desktops din YASB (acelasi config, aceleasi click-uri) cu:
  - clasa CSS `empty` pe butoanele desktop-urilor fara ferestre (in styles.css devin cercuri);
  - la hover, o lista cu numele fiecarui desktop si iconitele aplicatiilor de pe el
    (click pe un rand = treci pe desktop-ul acela);
  - callback-ul `switch_desktop N`, folosit de comenzile din lansator.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QFileInfo, QObject, QPoint, Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QFileIconProvider, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.utils.utilities import refresh_widget_style
from core.validation.widgets.yasb.desktops_plus import DesktopsPlusConfig
from core.widgets.services.windows_desktops.service import WindowsDesktopService
from core.widgets.yasb.windows_desktops import WorkspaceButton, WorkspaceWidget


@dataclass
class DesktopApp:
    process: str
    path: str
    title: str


def _enum_windows() -> list[int]:
    handles: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        handles.append(int(hwnd))
        return True

    ctypes.windll.user32.EnumWindows(proc(cb), 0)
    return handles


class _HoverPopup(QWidget):
    def __init__(self, owner: DesktopsPlusWidget):
        super().__init__(owner, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._owner = owner
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setProperty("class", "desktops-hover")
        self.rows = QVBoxLayout(self.frame)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        outer.addWidget(self.frame)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._owner._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._owner._hide_timer.start(250)
        super().leaveEvent(a0)


class _Row(QFrame):
    def __init__(self, number: int, owner: DesktopsPlusWidget):
        super().__init__()
        self.number = number
        self._owner = owner
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            WindowsDesktopService.switch_desktop(self.number)
            self._owner._hide_popup()


class DesktopsPlusWidget(WorkspaceWidget):
    validation_schema = DesktopsPlusConfig

    def __init__(self, config: DesktopsPlusConfig):
        super().__init__(config)
        self.config: DesktopsPlusConfig = config
        self._apps_by_desktop: dict[int, list[DesktopApp]] = {}
        self._windows: dict[int, object] = {}
        self._vdm = None
        self._icons: dict[str, QPixmap] = {}
        self._icon_provider = QFileIconProvider()
        self._ignored = {p.lower() for p in config.ignore_processes}
        self._popup: _HoverPopup | None = None

        self.register_callback("switch_desktop", self._cb_switch_desktop)

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_popup)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_popup)

        for btn in self.workspace_buttons:  # butoanele create de clasa de baza inainte de timere
            btn.installEventFilter(self)
            btn._mint_hover = True  # type: ignore[attr-defined]

        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._scan)
        self._scan_timer.start(config.scan_interval)
        QTimer.singleShot(200, self._scan)

    # ------------------------------------------------------------------ ferestre pe desktop-uri

    def _desktop_id(self, hwnd: int) -> str | None:
        try:
            if self._vdm is None:
                from core.utils.win32.bindings.ole32 import create_com_object
                from core.utils.win32.bindings.shell32 import CLSID_VirtualDesktopManager, IVirtualDesktopManager
                from core.utils.win32.constants import CLSCTX_INPROC_SERVER

                self._vdm = create_com_object(CLSID_VirtualDesktopManager, IVirtualDesktopManager, CLSCTX_INPROC_SERVER)
            guid = self._vdm.GetWindowDesktopId(hwnd)  # type: ignore[union-attr]
            if bytes(guid) == b"\x00" * 16:
                return None  # fereastra fara desktop (fixata pe toate sau fantoma)
            return str(guid).lower()
        except Exception:
            return None

    def _scan(self) -> None:
        try:
            from core.widgets.services.taskbar.application_window import ApplicationWindow

            by_guid = {d.guid.lower(): d.number for d in self._svc.get_desktops()}
            apps: dict[int, list[DesktopApp]] = {n: [] for n in by_guid.values()}
            alive: set[int] = set()
            own_pid = __import__("os").getpid()
            for hwnd in _enum_windows():
                win = self._windows.get(hwnd)
                if win is None:
                    win = ApplicationWindow(hwnd)
                    self._windows[hwnd] = win
                else:
                    win.update()  # type: ignore[attr-defined]
                alive.add(hwnd)
                if not win.is_taskbar_window():  # type: ignore[attr-defined]
                    continue
                if win.process_pid == own_pid or (win.process_name or "").lower() in self._ignored:  # type: ignore[attr-defined]
                    continue
                number = by_guid.get(self._desktop_id(hwnd) or "")
                if number is None:
                    continue
                apps[number].append(DesktopApp(win.process_name or "", win.process_path or "", win.title))  # type: ignore[attr-defined]
            for gone in set(self._windows) - alive:
                self._windows.pop(gone, None)
            changed = {n: [a.process for a in v] for n, v in apps.items()} != {
                n: [a.process for a in v] for n, v in self._apps_by_desktop.items()
            }
            self._apps_by_desktop = apps
            if changed:
                for btn in self.workspace_buttons:
                    self._apply_empty(btn)
                if self._popup is not None and self._popup.isVisible():
                    self._fill_popup()
        except Exception:
            logging.debug("desktops_plus: scanare esuata", exc_info=True)

    # ------------------------------------------------------------------ butoane

    def _apply_empty(self, btn: WorkspaceButton) -> None:
        apps = getattr(self, "_apps_by_desktop", None)
        if apps is None:
            return
        tokens = (btn.property("class") or "").split()
        is_active = "active" in tokens
        empty = not is_active and not apps.get(btn.workspace_index)
        new = [t for t in tokens if t != "empty"] + (["empty"] if empty else [])
        if new != tokens:
            btn.setProperty("class", " ".join(new))
            refresh_widget_style(btn)

    def _update_button(self, workspace_btn: WorkspaceButton, schedule_update: bool = True) -> None:
        super()._update_button(workspace_btn, schedule_update)
        self._apply_empty(workspace_btn)
        if not getattr(workspace_btn, "_mint_hover", False) and hasattr(self, "_show_timer"):
            workspace_btn.installEventFilter(self)
            workspace_btn._mint_hover = True  # type: ignore[attr-defined]

    def _cb_switch_desktop(self, number: str = "1") -> None:
        try:
            WindowsDesktopService.switch_desktop(int(number))
        except Exception:
            logging.exception("desktops_plus: nu pot trece pe desktop-ul %s", number)

    # ------------------------------------------------------------------ hover

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        if a1 is not None and isinstance(a0, WorkspaceButton) and self.config.hover.enabled:
            if a1.type() == QEvent.Type.Enter:
                self._hide_timer.stop()
                if self._popup is None or not self._popup.isVisible():
                    self._show_timer.start(self.config.hover.delay)
            elif a1.type() == QEvent.Type.Leave:
                self._show_timer.stop()
                self._hide_timer.start(250)
            elif a1.type() == QEvent.Type.MouseButtonPress:
                self._show_timer.stop()
                self._hide_popup()
        return super().eventFilter(a0, a1)

    def _icon(self, path: str) -> QPixmap | None:
        if not path:
            return None
        pm = self._icons.get(path)
        if pm is None:
            pm = self._icon_provider.icon(QFileInfo(path)).pixmap(14, 14)
            self._icons[path] = pm
        return pm

    def _fill_popup(self) -> None:
        popup = self._popup
        if popup is None:
            return
        while popup.rows.count():
            item = popup.rows.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()  # type: ignore[union-attr]
        current = self._svc.get_current_desktop().number
        hover = self.config.hover
        for d in self._svc.get_desktops():
            row = _Row(d.number, self)
            row.setProperty("class", "row active" if d.number == current else "row")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            num = QLabel(str(d.number))
            num.setProperty("class", "num")
            name = QLabel(d.name or hover.name_format.format(index=d.number))
            apps = self._apps_by_desktop.get(d.number, [])
            name.setProperty("class", "name" if apps or d.number == current else "name empty")
            lay.addWidget(num)
            lay.addWidget(name, 1)
            if apps:
                seen: set[str] = set()
                for app in apps:
                    key = app.path or app.process
                    if key in seen:
                        continue
                    seen.add(key)
                    if len(seen) > hover.max_icons:
                        break
                    icon = QLabel()
                    icon.setProperty("class", "app-icon")
                    pm = self._icon(app.path)
                    if pm is not None and not pm.isNull():
                        icon.setPixmap(pm)
                    else:
                        icon.setText(app.process[:1].upper())
                    icon.setToolTip(app.title)
                    lay.addWidget(icon)
            else:
                empty = QLabel(hover.empty_label)
                empty.setProperty("class", "empty")
                lay.addWidget(empty)
            popup.rows.addWidget(row)
        popup.adjustSize()

    def _show_popup(self) -> None:
        if self._popup is None:
            self._popup = _HoverPopup(self)
        self._fill_popup()
        popup = self._popup
        pos = self.mapToGlobal(QPoint(0, self.height() + 6))
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
        if screen is not None:
            geo = screen.geometry()
            pos.setX(max(geo.left(), min(pos.x(), geo.right() - popup.width())))
        popup.move(pos)
        popup.show()

    def _hide_popup(self) -> None:
        if self._popup is not None:
            self._popup.hide()
