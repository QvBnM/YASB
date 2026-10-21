"""
Branch-ul git al proiectului deschis in VS Code (sau Cursor / VSCodium).

Numele folderului vine din titlul ferestrei ("fisier - proiect - Visual Studio Code");
folderul e cautat in `roots`. Starea vine din `git status --porcelain=v2 --branch`,
rulat pe un fir separat, fara fereastra de consola.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass

from PyQt6.QtCore import QTimer, pyqtSignal

from core.validation.widgets.yasb.git_branch import GitBranchConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb.mint_common import fill_labels, foreground, toggle_alt

EDITOR_TITLES = ("Visual Studio Code", "Cursor", "VSCodium")
CREATE_NO_WINDOW = 0x08000000
INDEX_TTL = 300.0


@dataclass
class GitState:
    repo: str = ""
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    changes: int = 0


def folder_from_title(title: str) -> str | None:
    """'● auth.ts - myrepo [WSL: Ubuntu] - Visual Studio Code' -> 'myrepo'"""
    parts = [p.strip() for p in title.split(" - ")]
    for i, part in enumerate(parts):
        if any(part.startswith(t) for t in EDITOR_TITLES) and i >= 1:
            folder = parts[i - 1].lstrip("● ").strip()
            folder = re.sub(r"\s*\[.*?\]$", "", folder)
            folder = re.sub(r"\s*\((Workspace|Spațiu de lucru)\)$", "", folder)
            return folder or None
    return None


def parse_status(output: str) -> GitState:
    st = GitState()
    oid = ""
    for line in output.splitlines():
        if line.startswith("# branch.head "):
            st.branch = line[len("# branch.head ") :].strip()
        elif line.startswith("# branch.oid "):
            oid = line[len("# branch.oid ") :].strip()
        elif line.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
            if m:
                st.ahead, st.behind = int(m.group(1)), int(m.group(2))
        elif line and not line.startswith("#"):
            st.changes += 1
    if st.branch == "(detached)":
        st.branch = oid[:7] or "detached"
    return st


class GitBranchWidget(BaseWidget):
    validation_schema = GitBranchConfig
    _state_ready = pyqtSignal(object)

    def __init__(self, config: GitBranchConfig):
        super().__init__(class_name=f"git-branch-widget {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._index: dict[str, str] = {}
        self._index_at = 0.0
        self._repo_path: str | None = None
        self._busy = False
        self._state: GitState | None = None
        self._editors = {e.lower() for e in config.editors}
        self._init_container()
        self.build_widget_label(config.label, config.label_alt)
        self.register_callback("toggle_label", self._toggle)
        self.register_callback("open_terminal", self._open_terminal)
        self.callback_left = config.callbacks.on_left
        self.callback_right = config.callbacks.on_right
        self.callback_middle = config.callbacks.on_middle
        self._state_ready.connect(self._on_state)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(config.update_interval)
        visibility.request(self, visibility.SELF, False)
        QTimer.singleShot(400, self._update)

    # ------------------------------------------------------------------ repo-uri

    def _build_index(self) -> None:
        index: dict[str, str] = {}
        for root in self.config.roots:
            root = os.path.expandvars(os.path.expanduser(root))
            try:
                for entry in os.scandir(root):
                    if not entry.is_dir():
                        continue
                    if os.path.isdir(os.path.join(entry.path, ".git")):
                        index.setdefault(entry.name.lower(), entry.path)
                        continue
                    try:
                        for sub in os.scandir(entry.path):
                            if sub.is_dir() and os.path.isdir(os.path.join(sub.path, ".git")):
                                index.setdefault(sub.name.lower(), sub.path)
                    except OSError:
                        pass
            except OSError:
                logging.debug("git_branch: nu pot citi %s", root)
        self._index = index
        self._index_at = time.monotonic()

    def _repo_for_foreground(self) -> str | None:
        fg = foreground()
        if fg.exe.lower() not in self._editors:
            return self._repo_path if self.config.keep_last else None
        folder = folder_from_title(fg.title)
        if not folder:
            return None
        stale = time.monotonic() - self._index_at
        # reindexam cand lista a expirat sau cand folderul nu e in ea, dar nu mai des de 10 s
        if (stale > INDEX_TTL or folder.lower() not in self._index) and stale > 10:
            self._build_index()
        return self._index.get(folder.lower())

    # ------------------------------------------------------------------ actualizare

    def _update(self) -> None:
        path = self._repo_for_foreground()
        self._repo_path = path
        if not path:
            self._set_hidden(True)
            return
        if self._busy:
            return
        self._busy = True

        def work():
            try:
                out = subprocess.run(
                    ["git", "-C", path, "status", "--porcelain=v2", "--branch"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                ).stdout
                st = parse_status(out)
                st.repo = os.path.basename(path)
            except Exception:
                logging.debug("git_branch: git status esuat", exc_info=True)
                st = None
            try:
                self._state_ready.emit(st)
            except RuntimeError:
                pass

        threading.Thread(target=work, name="mint-git", daemon=True).start()

    def _on_state(self, st: GitState | None) -> None:
        self._busy = False
        self._state = st
        if not st or not st.branch:
            self._set_hidden(True)
            return
        self._set_hidden(False)
        self._render()

    def _render(self) -> None:
        st = self._state
        if not st:
            return
        sync = " ".join(x for x in (f"↑{st.ahead}" if st.ahead else "", f"↓{st.behind}" if st.behind else "") if x)
        dirty = f"~{st.changes}" if st.changes else ""
        extra = " ".join(x for x in (sync, dirty) if x)
        fill_labels(
            self,
            {
                "branch": st.branch,
                "repo": st.repo,
                "ahead": st.ahead,
                "behind": st.behind,
                "changes": st.changes,
                "sync": (" " + sync) if sync else "",
                "dirty": (" " + dirty) if dirty else "",
                "extra": (" " + extra) if extra else "",
            },
        )

    def _set_hidden(self, hidden: bool) -> None:
        visibility.request(self, visibility.SELF, not hidden)

    def _toggle(self) -> None:
        toggle_alt(self)
        self._render()

    def _open_terminal(self) -> None:
        if self._repo_path:
            subprocess.Popen(["wt.exe", "-d", self._repo_path], creationflags=CREATE_NO_WINDOW)

    def showEvent(self, a0) -> None:  # noqa: N802 - nume Qt
        super().showEvent(a0)
        # aratat de context_mode: verificam imediat, nu peste 3 secunde
        QTimer.singleShot(0, self._update)
