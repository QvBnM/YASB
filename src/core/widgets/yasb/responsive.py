"""
Responsive bar: the same config on a 2560 px PC and a 1920 px laptop at 125 % (1536 px for Qt).

Invisible widget, one per bar. Every second it measures what the three columns need and, when
that is more than the bar is wide, hides the least important widgets of the side that asks for
the most room, in the configured order; they come back one by one as soon as there is room
again. Only widgets it hid itself are ever shown again, so widgets that hide on their own
(Bluetooth without a radio, the visualizer without music, modes) are left alone.
The bar also gets a tier class (tier-full / tier-normal / tier-dense / tier-min) chosen from
the room left beside the clock, which styles.css uses for tighter spacing and smaller text.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from core.events.service import EventService
from core.utils.qobject import is_valid_qobject
from core.validation.widgets.yasb.responsive import TIERS, ResponsiveConfig
from core.widgets.base import BaseWidget
from core.widgets.yasb import mint_visibility as visibility
from core.widgets.yasb import mint_health as health
from core.widgets.yasb.bar_overflow import HIDDEN_EVENT
from core.widgets.yasb.mint_common import all_bar_widgets, find_named, make_invisible, refresh_tree, set_class_token


Entry = tuple[str, int, bool]  # name, width in px, hidden by us


def plan_bar(budget: int, fixed: int, sides: dict[str, tuple[int, list[Entry]]], hysteresis: int) -> tuple[list[str], list[str]]:
    """
    Ce dispare si ce se intoarce, socotit pe toata bara.

    budget = latimea barei, minus marginea
    fixed  = cat cer coloanele de care nu ne ocupam (mijlocul)
    sides  = {"left": (cat cere coloana, ordinea de ascundere), "right": (...)}
             ordinea incepe cu cel mai putin important.

    Prima versiune socotea fiecare latura separat, cu (latime - ceas) / 2 de fiecare parte:
    adica cerea ca ceasul sa stea exact la mijloc. Pe bara ta, cu partea dreapta mult mai
    incarcata, iesea ca dreapta are 682 px si cere mai mult, asa ca ascundea sase widget-uri
    degeaba — bara, de fapt, incapea. Qt oricum nu centreaza coloana din mijloc: cele trei
    coloane isi iau locul dupa cat au nevoie. Deci socotim o singura data, pe toata bara, si
    ascundem numai atat cat lipseste — de partea care cere mai mult.
    """
    needs = {key: need for key, (need, _order) in sides.items()}
    queues = {key: [e for e in order if not e[2] and e[1] > 0] for key, (_need, order) in sides.items()}
    to_hide: list[str] = []
    total = fixed + sum(needs.values())
    while total > budget:
        side = max((k for k in queues if queues[k]), key=lambda k: needs[k], default=None)
        if side is None:
            break  # nu mai avem ce ascunde: bara rabufneste, dar nu mai putem face nimic
        name, width, _ = queues[side].pop(0)
        to_hide.append(name)
        needs[side] -= width
        total -= width
    if to_hide:
        return to_hide, []
    # A mai ramas loc: aducem inapoi un singur widget pe masuratoare, cel mai important din
    # cele ascunse de pe fiecare latura, si doar daca incape cu rezerva. Unul singur, ca sa
    # fie masurat din nou inainte de urmatorul: asa nu se intoarce un val intreg care nu incape.
    slack = budget - total
    candidates: list[Entry] = []
    for _need, order in sides.values():
        mine = [e for e in order if e[2]]
        if mine:
            candidates.append(mine[-1])  # ultimul din ordine = cel mai important
    candidates.sort(key=lambda e: e[1])  # cel mai ingust intai: are cele mai mari sanse sa ramana
    for name, width, _ in candidates:
        if width + hysteresis <= slack:
            return [], [name]
    return [], []


def next_tier(
    current: str,
    need: int,
    essential: int,
    budget: int,
    known: dict[str, int],
    hysteresis: int,
    squeeze_to: str = "normal",
    cap: str = "full",
) -> str:
    """
    Nivelul urmator, dintr-o masuratoare adevarata. Un singur pas pe masuratoare.

    need      = cat cere bara acum, cu tot ce se vede
    essential = cat cere fara widget-urile pe care avem voie sa le ascundem
    budget    = cat are bara
    known     = cat cerea bara ultima data cand a fost la fiecare nivel

    Prima versiune alegea nivelul dintr-un prag de pixeli: sub 820 px pe o latura, bara trecea
    pe "normal" si primea clasa "compact". Laptopul tau (1536 px) cade mereu sub pragul ala,
    deci bara era strasa permanent, cu spatiile injumatatite -- de aici "nu mai intra un ac".
    Pragul nu stia nimic despre widget-urile tale; masuratoarea stie.

    Ordinea in care cedam, de la ce se simte mai putin la ce se simte mai mult:
      1. strangem spatiile un pas (pana la `squeeze_to`);
      2. ascundem widget-urile neimportante (nu aici, vezi plan_bar);
      3. strangem mai mult -- doar daca nici baza (ceas, titlu, stari) nu mai incape.
    Inapoi urcam doar cand stim sigur ca incape: cat cerea bara la nivelul de deasupra e
    masurat, nu ghicit, deci nu putem ajunge sa urcam si sa coboram la fiecare secunda.
    """
    top = min(TIERS.index(cap), len(TIERS) - 1)
    i = TIERS.index(current)
    if i > top:
        return TIERS[top]
    floor = min(TIERS.index(squeeze_to), top)
    if need > budget and i > floor:
        return TIERS[i - 1]  # strangem, dar nu sub nivelul cerut
    if essential > budget and i > 0:
        return TIERS[i - 1]  # nici baza nu incape: ecran chiar ingust
    if need <= budget and i < top:
        predicted = known.get(TIERS[i + 1])
        if predicted is not None and predicted + hysteresis <= budget:
            return TIERS[i + 1]
    return current


def _really_hidden(widget) -> bool:
    try:
        return widget.isHidden()
    except RuntimeError:
        return False


def at_or_below(tier: str, limit: str) -> bool:
    """True when `tier` is as tight as `limit`, or tighter."""
    return TIERS.index(tier) <= TIERS.index(limit)


UNIT_HIDDEN = "_mint_unit_hidden"
LAST_WIDTH = "_mint_last_width"  # cat ocupa widget-ul cand se vedea ultima data


def units_to_change(labels, show: bool) -> tuple[list, list]:
    """
    Which unit labels to hide / show, following the same rule as whole widgets: hide anything,
    but only ever show back what we hid ourselves.

    Without that rule this un-hid the *alt* labels too. A widget's alt label set is hidden by
    YASB until you click it, so the bar ended up reading "CPU 17% MHz 55°C": the percent from
    the normal label, and MHz from the alt one, side by side.
    """
    to_hide, to_show = [], []
    for label in labels:
        if not show:
            if not label.isHidden():
                to_hide.append(label)
        elif label.isHidden() and getattr(label, UNIT_HIDDEN, False):
            to_show.append(label)
    return to_hide, to_show


class ResponsiveWidget(BaseWidget):
    validation_schema = ResponsiveConfig

    def __init__(self, config: ResponsiveConfig):
        super().__init__(class_name="responsive")
        self.config = config
        make_invisible(self)
        self._tier: str | None = None
        self._need_at: dict[str, int] = {}  # cat cerea bara ultima data la fiecare nivel
        self._watched: QWidget | None = None
        self._clock_column: QWidget | None = None
        self._overflow_widget: QWidget | None = None
        self._announced: str | None = None
        self._events = EventService()
        self._timer = QTimer(self)
        health.connect(self._timer, "responsive", self._tick)
        self.register_callback("show_health", self._show_health)
        self._timer.start(config.interval)
        QTimer.singleShot(600, self._tick)
        self._watch_screens()

    # ------------------------------------------------------------------ monitoare

    def _watch_screens(self) -> None:
        """
        Cand conectezi sau scoti un monitor, tot ce stiam despre bara devine vechi.

        Pana acum ramaneau referintele vechi la cadrul barei si la ceas, iar bara se stramba
        pana o reporneai. Acum le aruncam si masuram din nou.
        """
        app = QApplication.instance()
        if app is None:
            return
        for signal in (app.screenAdded, app.screenRemoved, app.primaryScreenChanged):
            signal.connect(self._screens_changed)

    def _screens_changed(self, *_args) -> None:
        self._watched = None
        self._tier = None
        self._need_at.clear()
        self._clock_column = None
        QTimer.singleShot(0, self._tick)
        QTimer.singleShot(400, self._tick)  # Qt aseaza barele din nou: mai masuram o data dupa

    # ------------------------------------------------------------------ helpers

    def _frame(self, root: QWidget) -> QWidget:
        for w in [root, *root.findChildren(QWidget)]:
            if "yasb-bar" in (w.property("class") or "").split():
                return w
        return root

    @staticmethod
    def _column(widget: QWidget, frame: QWidget) -> QWidget | None:
        """The bar column (left / center / right container) that holds this widget."""
        w = widget
        while w is not None and w.parentWidget() is not None and w.parentWidget() is not frame:
            w = w.parentWidget()
        return w if w is not None and w.parentWidget() is frame else None

    @staticmethod
    def _hint(w: QWidget) -> int:
        lay = w.layout()
        if lay is not None:
            lay.invalidate()
        return max(0, w.sizeHint().width())

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        if a1 is not None and a1.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._tick)
        return False

    # ------------------------------------------------------------------ main

    def _tick(self) -> None:
        try:
            self._apply()
        except RuntimeError:
            pass  # a widget was destroyed mid-measure: the next tick sees the new bar
        except Exception as exc:
            health.failed("responsive", exc, self._timer.stop)

    def _show_health(self) -> None:
        """Panoul „Starea barei”, deschis din lansator. Se aseaza sub mijlocul barei."""
        root = self.window()
        if root is None or root is self:
            return
        health.show_panel(self._frame(root))

    def _overflow(self, root: QWidget):
        """Sageata de la capatul barei, daca exista in bara asta."""
        if self._overflow_widget is not None and is_valid_qobject(self._overflow_widget):
            return self._overflow_widget
        from core.widgets.yasb.bar_overflow import BarOverflowWidget

        self._overflow_widget = next((w for w in all_bar_widgets(root) if isinstance(w, BarOverflowWidget)), None)
        return self._overflow_widget

    def _portrait(self, frame: QWidget) -> bool:
        screen = frame.screen()
        if screen is None:
            return False
        geometry = screen.geometry()
        return geometry.height() > geometry.width()

    def _set_tier(self, frame: QWidget, tier: str) -> None:
        if tier == self._tier:
            return
        self._tier = tier
        set_class_token(frame, f"tier-{tier}", True, prefix="tier-")
        # "compact" ramane pentru regulile scrise inainte de niveluri
        set_class_token(frame, "compact", tier != "full")
        self._apply_units(frame, tier)
        refresh_tree(frame)

    def _apply_units(self, frame: QWidget, tier: str) -> None:
        """
        Unitatile (%, grade) se scriu doar cand e loc.

        Qt nu cunoaste "display: none", deci asta nu se poate face din stiluri. Etichetele de
        unitate nu sunt widget-uri de bara, deci nu trec prin arbitru: nimeni altcineva nu le
        atinge vizibilitatea.
        """
        show = not at_or_below(tier, self.config.hide_units_from)
        units = [lb for lb in frame.findChildren(QLabel) if "unit" in (lb.property("class") or "").split()]
        to_hide, to_show = units_to_change(units, show)
        for label in to_hide:
            setattr(label, UNIT_HIDDEN, True)
            label.setVisible(False)
        for label in to_show:
            setattr(label, UNIT_HIDDEN, False)
            label.setVisible(True)

    def _apply(self) -> None:
        root = self.window()
        if root is None or root is self:
            return
        frame = self._frame(root)
        if self._watched is not frame:
            frame.installEventFilter(self)
            self._watched = frame
        width = frame.width()
        if width <= 0:
            return

        names = {n for n in self.config.hide_left + self.config.hide_right + list(self.config.flexible)}
        names |= {"clock"}
        found: dict[str, QWidget] = {}
        for w in find_named(names, root):
            found.setdefault(w.widget_name, w)  # type: ignore[attr-defined]

        overflow = self._overflow(root)

        budget = width - self.config.margin
        sides: dict[str, tuple[int, list[Entry]]] = {}
        columns: dict[str, QWidget] = {}
        for key, side in (("left", self.config.hide_left), ("right", self.config.hide_right)):
            widgets = [(n, found[n]) for n in side if n in found]
            if not widgets:
                continue
            column = self._column(widgets[0][1], frame)
            if column is None:
                continue
            columns[key] = column
            need = self._hint(column)
            # The arrow at the end of the bar appears exactly when we hide something, and it
            # takes room itself — so it could cause the very hiding that made it appear, and
            # then oscillate as things come back. We keep its room reserved either way, and
            # leave it out of the measurement, so it never enters the arithmetic.
            if overflow is not None and self._column(overflow, frame) is column:
                reserve = self._hint(overflow)
                budget -= reserve
                if not overflow.isHidden():
                    need = max(0, need - max(reserve, overflow.width()))
            # flexible widgets (the window title) only count with their minimum
            for name, minimum in self.config.flexible.items():
                fw = found.get(name)
                if fw is not None and not fw.isHidden() and self._column(fw, frame) is column:
                    need += minimum - self._hint(fw)
            sides[key] = (need, self._order(widgets))

        # coloanele de care nu ne ocupam (mijlocul, si o latura fara widget-uri de ascuns)
        fixed = sum(self._hint(c) for c in self._columns(frame) if c not in columns.values())
        if not sides:
            self._announce(found)
            return

        # Nivelul se hotaraste din masuratoarea asta, nu dintr-un prag de pixeli: cat cere bara
        # fata de cat are. "Esential" e cat ar cere si daca am ascunde tot ce avem voie.
        if self._tier is None:
            self._set_tier(frame, TIERS[-1])  # pornim larg si strangem doar daca e nevoie
        need = fixed + sum(n for n, _ in sides.values())
        essential = fixed + sum(n - sum(w for _, w, hid in order if not hid) for n, order in sides.values())
        tier = self._tier or TIERS[-1]  # None nu mai e posibil aici, dar type checker-ul nu stie
        self._need_at[tier] = need
        wanted = next_tier(
            tier,
            need,
            essential,
            budget,
            self._need_at,
            self.config.hysteresis,
            self.config.squeeze_to,
            self.config.portrait_max_tier if self._portrait(frame) else TIERS[-1],
        )
        if wanted != tier:
            logging.info(
                "responsive: bara %dpx, loc %dpx, cerut %dpx -> nivel %s", width, budget, need, wanted
            )
            self._set_tier(frame, wanted)
            self._announce(found)
            return  # masuram din nou cu spatiile noi inainte sa ascundem ceva

        to_hide, to_show = plan_bar(budget, fixed, sides, self.config.hysteresis)
        for name in to_hide:
            visibility.request(found[name], visibility.SPACE, False)
        for name in to_show:
            visibility.request(found[name], visibility.SPACE, True)
        if to_hide or to_show:
            logging.info(
                "responsive: bara %dpx, loc %dpx, cerut %dpx -> ascuns %s, aratat %s",
                width,
                budget,
                fixed + sum(need for need, _ in sides.values()),
                to_hide,
                to_show,
            )
        self._announce(found)

    def _columns(self, frame: QWidget) -> list[QWidget]:
        """Cele trei coloane ale barei (stanga / mijloc / dreapta), copii direcți ai cadrului."""
        return [
            w
            for w in frame.findChildren(QWidget)
            if w.parentWidget() is frame and "container" in (w.property("class") or "").split()
        ]

    def _order(self, widgets: list[tuple[str, QWidget]]) -> list[Entry]:
        """Ordinea de ascundere a unei laturi, cu latimea pe care o ocupa fiecare."""
        order: list[Entry] = []
        for name, w in widgets:
            if visibility.escaped(w):
                logging.info("responsive: %s se arata singur; nu mai socotesc ca l-am ascuns", name)
            if visibility.self_managed(w):
                continue  # se ocupa singur: ocupa loc si il lasam in pace
            # a widget a mode hid, or that hid itself for want of data, is not ours to manage:
            # we only ever decide about room (see mint_visibility)
            if not (visibility.wants(w, visibility.MODE) and visibility.wants(w, visibility.SELF)):
                continue
            hidden_by_us = not visibility.wants(w, visibility.SPACE)
            if w.isHidden() and not hidden_by_us:
                continue  # hidden by YASB itself (media with hide_empty): not ours either
            order.append((name, self._width_of(w, hidden_by_us), hidden_by_us))
        return order

    @staticmethod
    def _width_of(w: QWidget, hidden_by_us: bool) -> int:
        """
        Cat loc ocupa widget-ul — aceeasi cifra la ascundere si la intoarcere.

        Ascuns, un widget nu mai are latime, iar sizeHint-ul lui iese alta cifra decat cat
        ocupa de fapt pe bara. De aici palpairea din jurnal: scadeam 90 px cand il ascundeam
        si socoteam 60 px cand verificam daca incape, deci incapea, il aduceam inapoi, nu
        incapea, il ascundeam din nou — la fiecare secunda. Acum tinem minte latimea reala de
        dinainte de ascundere si o folosim pe ea.
        """
        if not hidden_by_us:
            real = max(1, w.width() or ResponsiveWidget._hint(w))
            setattr(w, LAST_WIDTH, real)
            return real
        return getattr(w, LAST_WIDTH, 0) or ResponsiveWidget._hint(w)

    def _announce(self, found: dict[str, QWidget]) -> None:
        """
        Spune cine a ramas pe dinafara, ca butonul de la capatul barei sa stie ce sa arate.

        Numai ce am ascuns noi din lipsa de loc: ce ascunde un mod, sau widget-ul insusi fiindca
        n-are ce arata, nu e "pe dinafara" — e ascuns cu rost.
        """
        # „ascuns de noi” nu e totuna cu „ascuns pe ecran”: unele widget-uri YASB se arata
        # singure dupa ce le-am ascuns, iar atunci lista de la capatul barei ar fi spus
        # „pe dinafara” despre ceva ce se vede. Cerem amandoua conditiile.
        hidden = sorted(
            name
            for name, w in found.items()
            if not visibility.wants(w, visibility.SPACE) and _really_hidden(w)
        )
        # Vestea pleaca pe un canal comun tuturor barelor, deci spunem si cine o trimite:
        # altfel bara de pe celalalt monitor crede ca e despre widget-urile ei.
        payload = f"{getattr(self, 'bar_id', '')}|" + ",".join(hidden)
        if payload == self._announced:
            return
        self._announced = payload
        self._events.emit_event(HIDDEN_EVENT, payload)
