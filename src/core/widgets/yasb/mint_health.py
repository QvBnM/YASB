"""
Bara se pazeste singura: nicio piesa nu poate darama restul.

Fiecare widget care bate pe un cronometru isi tine socoteala aici: de cate ori a mers, cat a
durat, ce eroare a dat ultima oara. Daca una da eroare de trei ori in zece minute, isi opreste
cronometrul, scrie un rand in jurnal si bara merge inainte fara ea.

De ce asa: pana acum, un widget care incepea sa crape la fiecare tick scria un traceback la
fiecare secunda in yasb.log si consuma procesor degeaba, la nesfarsit. Iar tu aflai despre el
abia cand deschideai jurnalul.

Ce NU scriem in jurnal: mesajul exceptiei. El poate contine un titlu de fereastra, o cale sau
un nume de retea. Scriem tipul exceptiei si widget-ul, atat; traceback-ul intreg ramane pe
nivelul de depanare, unde ajunge doar daca il ceri.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

# Trei greseli intr-un sfert de ora inseamna ca nu a fost o intamplare.
ERROR_LIMIT = 3
ERROR_WINDOW = 600.0  # secunde


@dataclass
class Status:
    """Cum o duce un widget."""

    name: str
    ticks: int = 0
    last_tick: float = 0.0
    total_ms: float = 0.0
    errors: int = 0
    last_error: str = ""
    stopped: bool = False
    stop_reason: str = ""
    _recent: list[float] = field(default_factory=list)

    @property
    def average_ms(self) -> float:
        return self.total_ms / self.ticks if self.ticks else 0.0

    def to_line(self) -> str:
        if self.stopped:
            return f"{self.name}: OPRIT ({self.stop_reason})"
        if not self.ticks:
            return f"{self.name}: inca nu a pornit"
        age = time.monotonic() - self.last_tick
        errors = f", {self.errors} erori" if self.errors else ""
        return f"{self.name}: {self.ticks} treceri, {self.average_ms:.1f} ms, acum {age:.0f}s{errors}"


_STATUS: dict[str, Status] = {}


def should_stop(recent: list[float], now: float, limit: int = ERROR_LIMIT, window: float = ERROR_WINDOW) -> bool:
    """Au fost destule greseli, destul de aproape una de alta, cat sa oprim functia?"""
    return len([t for t in recent if now - t <= window]) >= limit


def status(name: str) -> Status:
    if name not in _STATUS:
        _STATUS[name] = Status(name)
    return _STATUS[name]


def report() -> list[Status]:
    """Toate piesele, cele oprite primele, apoi cele cu erori."""
    return sorted(_STATUS.values(), key=lambda s: (not s.stopped, s.errors == 0, s.name))


def reset(name: str | None = None) -> None:
    if name is None:
        _STATUS.clear()
    else:
        _STATUS.pop(name, None)


def failed(name: str, exc: BaseException, stop=None) -> bool:
    """
    Un widget a dat de o eroare (si pe cele pe care le prinde singur le trece pe aici).

    Intoarce True daca asta a fost picatura care l-a oprit.
    """
    state = status(name)
    now = time.monotonic()
    state.errors += 1
    state.last_error = type(exc).__name__
    state._recent.append(now)
    state._recent = [t for t in state._recent if now - t <= ERROR_WINDOW]
    logging.debug("mint: %s a dat eroare", name, exc_info=exc)
    if state.stopped or not should_stop(state._recent, now):
        logging.warning("mint: %s a dat eroare (%s)", name, state.last_error)
        return False
    state.stopped = True
    state.stop_reason = f"{ERROR_LIMIT} erori in {int(ERROR_WINDOW / 60)} minute ({state.last_error})"
    logging.warning("mint: %s s-a oprit singur dupa %s. Restul barei merge inainte.", name, state.stop_reason)
    if stop is not None:
        try:
            stop()
        except Exception:
            logging.debug("mint: nu pot opri cronometrul lui %s", name, exc_info=True)
    return True


def guard(name: str, fn, stop=None):
    """Imbraca functia unui cronometru: masoara cat dureaza, prinde erorile, si o opreste la nevoie."""
    state = status(name)

    def run() -> None:
        if state.stopped:
            return
        started = time.perf_counter()
        try:
            fn()
        except Exception as exc:
            failed(name, exc, stop)
            return
        state.ticks += 1
        state.last_tick = time.monotonic()
        state.total_ms += (time.perf_counter() - started) * 1000

    return run


def connect(timer, name: str, fn) -> None:
    """Leaga un cronometru de functia lui, trecuta prin paza."""
    timer.timeout.connect(guard(name, fn, stop=timer.stop))


# --------------------------------------------------------------------------- panoul


def show_panel(bar_frame, blur: bool = False) -> object | None:
    """
    Lista cu ce merge si ce nu, deschisa din lansator ("Starea barei").

    Se aseaza sub mijlocul barei, nu sub un widget anume: un widget ascuns n-are pozitie
    valida, iar panoul asta trebuie sa mearga tocmai cand ceva nu e in regula.
    """
    from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

    from core.utils.utilities import PopupWidget

    if bar_frame is None:
        return None
    popup = PopupWidget(bar_frame, blur, True, "normal", "None")
    popup.setProperty("class", "mint-health-panel")
    outer = QVBoxLayout(popup)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    header = QLabel("Starea barei")
    header.setProperty("class", "header")
    outer.addWidget(header)

    body = QFrame()
    body.setProperty("class", "body")
    rows = QVBoxLayout(body)
    rows.setSpacing(0)

    entries = report()
    if not entries:
        empty = QLabel("Nicio piesa nu a raportat inca.")
        empty.setProperty("class", "empty")
        rows.addWidget(empty)
    for state in entries:
        row = QFrame()
        row.setProperty("class", "row stopped" if state.stopped else ("row warn" if state.errors else "row"))
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        name = QLabel(state.name)
        name.setProperty("class", "name")
        detail = QLabel(_detail(state))
        detail.setProperty("class", "detail")
        line.addWidget(name)
        line.addStretch()
        line.addWidget(detail)
        rows.addWidget(row)
    outer.addWidget(body)

    popup.adjustSize()
    popup.setPosition(alignment="center", direction="down", offset_top=6)
    popup.show()
    return popup


def _detail(state: Status) -> str:
    if state.stopped:
        return f"oprit · {state.stop_reason}"
    if not state.ticks:
        return "inca nu a pornit"
    age = time.monotonic() - state.last_tick
    text = f"{state.average_ms:.1f} ms · acum {age:.0f}s"
    if state.errors:
        text += f" · {state.errors} erori ({state.last_error})"
    return text
