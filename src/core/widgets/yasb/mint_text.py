"""
Un singur traseu pentru textul din bara.

Trei lucruri rescriau aceeasi eticheta, fiecare inlocuind metoda setText peste ce gasea:
  - mint_thresholds, ca sa coloreze cifra cand trece pragul;
  - active_title, ca sa taie titlul ferestrei la latimea libera;
  - ui_polish, ca sa traduca in romana textele fixe din YASB.

Cine ajunge primul la o eticheta decidea ordinea, iar ordinea schimba rezultatul: traducerea
putea ajunge peste titlul unei ferestre, iar pragul putea fi calculat pe textul netradus.

Aici metoda e inlocuita o singura data, iar restul isi inregistreaza pasul lor cu o ordine
scrisa in clar. Textul brut (cel primit de la widget) e tinut deoparte, deci se poate reface
oricand de la capat — de exemplu cand se schimba latimea libera de langa ceas.
"""

from __future__ import annotations

import logging

# Ordinea pasilor. Traducerea vine prima: taierea la latime trebuie sa lucreze pe textul
# care chiar se va vedea, altfel am taia dupa lungimea celui netradus.
TRANSLATE = 10
FIT = 20

_STATE = "_mint_text"


def _state(label) -> dict:
    state = getattr(label, _STATE, None)
    if state is not None:
        return state
    state = {
        "stages": [],  # [(ordine, nume, functie)] - schimba textul
        "observers": [],  # [(nume, functie)] - privesc textul final (ex. culoarea de prag)
        "excluded": set(),  # pasi refuzati anume de widget (ex. titlul ferestrei nu se traduce)
        "raw": _current_text(label),
        "write": label.setText,  # metoda adevarata, luata inainte sa o inlocuim
    }
    try:
        setattr(label, _STATE, state)
    except AttributeError:
        return state  # obiect care nu primeste atribute: ii lasam textul in pace
    label.setText = lambda text, _l=label: _receive(_l, text)
    return state


def _current_text(label) -> str:
    try:
        return label.text() or ""
    except Exception:
        return ""


def _receive(label, text) -> None:
    """Widget-ul a scris un text nou: il tinem minte si il trecem prin pasi."""
    state = _state(label)
    state["raw"] = text if isinstance(text, str) else ("" if text is None else str(text))
    render(label)


def render(label) -> None:
    """Trece textul brut prin toti pasii si il scrie pe eticheta."""
    state = _state(label)
    text = state["raw"]
    for _order, name, step in state["stages"]:
        if name in state["excluded"]:
            continue
        try:
            text = step(text)
        except Exception:
            logging.debug("mint_text: pasul '%s' a esuat", name, exc_info=True)
    try:
        state["write"](text)
    except RuntimeError:
        return  # eticheta a fost distrusa intre timp
    for name, observer in state["observers"]:
        try:
            observer(text)
        except Exception:
            logging.debug("mint_text: observatorul '%s' a esuat", name, exc_info=True)


def add_stage(label, name: str, step, order: int) -> None:
    """Inregistreaza un pas care schimba textul. Acelasi nume se inlocuieste, nu se dubleaza."""
    state = _state(label)
    state["stages"] = sorted(
        [s for s in state["stages"] if s[1] != name] + [(order, name, step)],
        key=lambda s: s[0],
    )
    render(label)


def add_observer(label, name: str, observer) -> None:
    """Inregistreaza pe cineva care doar se uita la textul final (nu il schimba)."""
    state = _state(label)
    state["observers"] = [o for o in state["observers"] if o[0] != name] + [(name, observer)]
    render(label)


def exclude(label, name: str) -> None:
    """Eticheta asta nu trece prin pasul cu numele dat (titlul ferestrei nu se traduce)."""
    state = _state(label)
    state["excluded"].add(name)
    render(label)


def raw_text(label) -> str:
    """Textul asa cum l-a scris widget-ul, inainte de orice pas."""
    return _state(label)["raw"]


def is_installed(label) -> bool:
    return getattr(label, _STATE, None) is not None
