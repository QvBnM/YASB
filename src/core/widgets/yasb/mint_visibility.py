"""
Un singur sef pe vizibilitate.

Pana acum trei lucruri hotarau in acelasi timp daca un widget se vede: modurile automate,
widget-ul responsive (lipsa de loc) si widget-ul insusi (n-are ce arata). Fiecare chema
setVisible pe cronometrul lui, deci se contraziceau: temperatura procesorului reaparea singura
la fiecare doua secunde chiar daca modul de joc tocmai o ascunsese. De aici bara care sare.

Aici nimeni nu mai cheama setVisible. Fiecare isi spune doar parerea, pe numele lui:

    visibility.request(widget, MODE,  False)   # modul de joc: nu-ti sta locul aici
    visibility.request(widget, SPACE, True)    # e loc pe bara
    visibility.request(widget, SELF,  False)   # n-am ce arata (HWiNFO oprit)

Widget-ul se vede doar daca toti trei sunt de acord. Lipsa unei pareri inseamna "da".
Starea sta chiar pe widget, deci dispare odata cu el: nu tinem un registru care sa scurga
memorie sau sa pastreze widget-uri moarte.
"""

from __future__ import annotations

MODE = "mode"  # modurile automate: lucru, joc, apel
SPACE = "space"  # widget-ul responsive: nu mai incape pe bara
SELF = "self"  # widget-ul insusi: n-are ce arata

OWNERS = (MODE, SPACE, SELF)

_STATE = "_mint_visibility"
_OURS = "__ours"  # noi l-am ascuns, deci tot noi avem voie sa-l aratam
_ESCAPES = "__escapes"  # de cate ori s-a aratat singur dupa ce l-am ascuns
_SELF_MANAGED = "__self_managed"  # se ocupa singur de vizibilitate: nu-l mai atingem

ESCAPE_LIMIT = 2  # dupa atatea incercari pierdute, renuntam definitiv


def effective(state: dict[str, bool]) -> bool:
    """Se vede doar daca nimeni nu se opune. O parere lipsa inseamna "da"."""
    return all(state.get(owner, True) for owner in OWNERS)


def hidden_by(state: dict[str, bool]) -> list[str]:
    """Cine anume il tine ascuns. Pentru jurnal si pentru panoul de sanatate."""
    return [owner for owner in OWNERS if not state.get(owner, True)]


def state_of(widget) -> dict[str, bool]:
    state = getattr(widget, _STATE, None)
    if state is None:
        state = {}
        try:
            setattr(widget, _STATE, state)
        except AttributeError:
            return {}  # obiect care nu primeste atribute: il lasam in pace
    return state


def wants(widget, owner: str) -> bool:
    """Ce crede un anumit proprietar despre widget-ul asta."""
    return state_of(widget).get(owner, True)


def is_visible(widget) -> bool:
    """Daca widget-ul ar trebui sa se vada, dupa toate parerile de pana acum."""
    return effective(state_of(widget))


def request(widget, owner: str, visible: bool) -> bool:
    """
    Spune parerea unui proprietar. Intoarce True daca vizibilitatea chiar s-a schimbat.

    Se poate chema oricat de des: daca parerea e aceeasi, nu se intampla nimic, deci nu
    costa si nu produce palpairi.
    """
    state = state_of(widget)
    if not visible and state.get(_SELF_MANAGED):
        return False  # nu mai pretindem ca il ascundem: n-ar fi adevarat
    if state.get(owner) == visible:
        return False
    state[owner] = visible
    return apply(widget)


def self_managed(widget) -> bool:
    """Widget-ul care si-a luat singur vizibilitatea in mana. Nu-l mai socotim al nostru."""
    return bool(state_of(widget).get(_SELF_MANAGED))


def escaped(widget) -> bool:
    """
    L-am ascuns noi, dar el se vede. Inseamna ca se arata singur.

    Unele widget-uri YASB cheama show() la fiecare masuratoare proprie, daca au ce afisa:
    placa video o face la fiecare citire. Pana acum starea noastra spunea "ascuns" iar ecranul
    arata altceva, deci socoteala de loc ramanea greuata la nesfarsit: scadeam un widget care
    de fapt ocupa loc, deci ascundeam altele degeaba, iar lista de la capatul barei pomenea
    lucruri care se vedeau.

    Aici recunoastem ca am pierdut: stergem parerile care cereau ascunderea (ele oricum nu sunt
    respectate), iar dupa cateva incercari il lasam definitiv in pace. Intoarce True o singura
    data per scapare, ca sa se poata scrie in jurnal.
    """
    state = state_of(widget)
    if not state.get(_OURS):
        return False
    try:
        if widget.isHidden():
            return False
    except RuntimeError:
        return False
    state.pop(_OURS, None)
    for owner in OWNERS:
        if state.get(owner) is False:
            del state[owner]
    count = state.get(_ESCAPES, 0) + 1
    state[_ESCAPES] = count
    if count >= ESCAPE_LIMIT:
        state[_SELF_MANAGED] = True
    return True


def apply(widget) -> bool:
    """
    Pune pe widget ce au hotarat toti. Intoarce True daca s-a schimbat ceva.

    Regula de bun-simt: ascundem oricand, dar aratam doar ce am ascuns noi. Unele widget-uri
    YASB se ascund singure, din motivele lor (media fara melodie, cu hide_empty). Daca le-am
    arata la loc doar pentru ca noi n-avem nimic impotriva, ne-am bate cu ele la fiecare tick.
    """
    state = state_of(widget)
    wanted = effective(state)
    if not wanted and state.get(_SELF_MANAGED):
        return False
    try:
        # isHidden() spune daca a fost ascuns anume, nu daca il acopera un parinte ascuns:
        # exact ce ne trebuie, altfel am rescrie starea de fiecare data cand bara e ascunsa.
        currently_hidden = widget.isHidden()
        if wanted:
            if not currently_hidden or not state.get(_OURS):
                return False
            state.pop(_OURS, None)
            widget.setVisible(True)
        else:
            if currently_hidden:
                return False
            state[_OURS] = True
            widget.setVisible(False)
    except RuntimeError:
        return False  # widget-ul a fost distrus intre timp
    return True


def forget(widget, owner: str) -> bool:
    """Un proprietar nu mai are nicio parere (ex. functia lui s-a oprit)."""
    state = state_of(widget)
    if owner not in state:
        return False
    del state[owner]
    return apply(widget)
