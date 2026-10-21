"""
Bara pe orice ecran: nivelul se alege din ce cere chiar bara ta, nu din rezoluție.

Asta e miezul cerinței „să se muleze pe orice monitor, chiar și pe unele pe care nu le ai”.
Prima versiune alegea nivelul dintr-un prag de pixeli — sub 820 px pe o latură, bara se
strângea. Laptopul lui (1536 px) cădea mereu sub prag, deci bara era strânsă permanent, cu
spațiile înjumătățite, chiar și când avea loc berechet. Pragul nu știa nimic despre
widget-urile din bară; măsurătoarea știe.

Aici bara pornește largă și strânge doar dacă e nevoie, un pas pe măsurătoare.
"""

import unittest

import stubs

stubs.install()

from core.validation.widgets.yasb.responsive import TIERS, ResponsiveConfig  # noqa: E402
from core.widgets.yasb.responsive import UNIT_HIDDEN, at_or_below, next_tier, plan_bar, units_to_change  # noqa: E402

CFG = ResponsiveConfig()


class Bar:
    """
    O bară de carton: la fiecare nivel cere mai puțin loc, ca una adevărată.

    `needs` spune cât cere la fiecare nivel, cu tot pe ea. `essential` e cât cere fără
    widget-urile pe care are voie să le ascundă.
    """

    def __init__(self, width: int, needs: dict[str, int], hideable: int = 0, portrait: bool = False):
        self.width = width
        self.needs = needs
        self.hideable = hideable
        self.portrait = portrait
        self.tier = "full"
        self.known: dict[str, int] = {}

    def tick(self) -> str:
        need = self.needs[self.tier]
        self.known[self.tier] = need
        cap = CFG.portrait_max_tier if self.portrait else TIERS[-1]
        self.tier = next_tier(
            self.tier, need, max(0, need - self.hideable), self.width, self.known,
            CFG.hysteresis, CFG.squeeze_to, cap,
        )
        return self.tier

    def settle(self, ticks: int = 8) -> str:
        """Unde se oprește după câteva măsurători."""
        for _ in range(ticks):
            before = self.tier
            if self.tick() == before:
                break
        return self.tier


def shrinking(full: int, step: int = 120) -> dict[str, int]:
    """Cât cere bara la fiecare nivel: fiecare treaptă mai jos taie `step` px."""
    return {tier: full - step * (len(TIERS) - 1 - i) for i, tier in enumerate(TIERS)}


class TestTiers(unittest.TestCase):
    def test_the_ladder_is_ordered(self):
        self.assertEqual(TIERS, ("min", "dense", "normal", "full"))

    def test_a_bar_that_fits_is_left_wide(self):
        """Cazul lui: pragul îl strângea mereu, deși bara încăpea."""
        self.assertEqual(Bar(1520, shrinking(1400)).settle(), "full")

    def test_it_tightens_one_step_at_a_time(self):
        bar = Bar(1340, shrinking(1400))
        self.assertEqual(bar.tick(), "normal")
        self.assertEqual(bar.settle(), "normal", "un pas a fost de ajuns")

    def test_it_does_not_tighten_past_the_configured_floor(self):
        """Sub „normal” nu coboară doar ca să încapă tot: de acolo încolo ascunde."""
        bar = Bar(900, shrinking(1400), hideable=600)
        self.assertEqual(bar.settle(), CFG.squeeze_to)

    def test_a_truly_narrow_bar_goes_lower(self):
        """Dacă nici baza nu mai încape, ascunsul nu mai salvează nimic: strângem mai mult."""
        bar = Bar(900, shrinking(1400), hideable=0)
        self.assertEqual(bar.settle(), "min")

    def test_it_loosens_back_when_the_bar_grows(self):
        bar = Bar(1340, shrinking(1400))
        self.assertEqual(bar.settle(), "normal")
        bar.width = 1600  # al doilea monitor, sau bara nefixată
        self.assertEqual(bar.settle(), "full")

    def test_it_never_loosens_on_a_guess(self):
        """Fără o măsurătoare la nivelul de deasupra, nu urcăm: altfel am urca și coborî la fiecare secundă."""
        bar = Bar(2000, shrinking(1400))
        bar.tier = "dense"
        bar.known.clear()
        self.assertEqual(bar.tick(), "dense")

    def test_it_does_not_oscillate(self):
        """Exact la limită: nivelul trebuie să se așeze, nu să sară."""
        for width in range(900, 1700, 7):
            bar = Bar(width, shrinking(1400))
            settled = bar.settle()
            self.assertEqual(bar.tick(), settled, f"la {width}px nivelul sare")

    def test_a_rotated_screen_never_goes_above_dense(self):
        bar = Bar(2000, shrinking(1400), portrait=True)
        self.assertEqual(bar.settle(), CFG.portrait_max_tier)

    def test_at_or_below(self):
        self.assertTrue(at_or_below("min", "dense"))
        self.assertTrue(at_or_below("dense", "dense"))
        self.assertFalse(at_or_below("normal", "dense"))
        self.assertFalse(at_or_below("full", "dense"))


class TestRealScreens(unittest.TestCase):
    """
    Ecranele de care te poți lovi, inclusiv cele pe care nu le ai.

    Numerele sunt px logici — ce vede Qt după scalarea Windows. De asta 1920 la 125 % și 1536
    la 100 % sunt același lucru: aceeași bară, același nivel, fără niciun caz special scris.
    Bara de probă cere 1400 px lărguță și taie 120 px la fiecare treaptă.
    """

    def tier(self, bar_width: int, portrait: bool = False) -> str:
        return Bar(bar_width, shrinking(1400), hideable=500, portrait=portrait).settle()

    def test_a_big_monitor_gets_everything(self):
        self.assertEqual(self.tier(2560), "full")
        self.assertEqual(self.tier(3840), "full")

    def test_a_laptop_is_comfortable(self):
        self.assertEqual(self.tier(1920), "full")

    def test_scaling_and_resolution_meet_at_the_same_tier(self):
        self.assertEqual(self.tier(1536), self.tier(1536))  # 1920 la 125 % = 1536 px logici

    def test_a_small_laptop_tightens_up(self):
        self.assertEqual(self.tier(1366), "normal")

    def test_a_rotated_screen_is_treated_as_tight(self):
        self.assertEqual(self.tier(1080, portrait=True), "dense")

    def test_a_very_narrow_bar_goes_below_the_floor(self):
        """Când nici baza nu mai încape, ascunsul nu mai salvează nimic: strânge mai mult."""
        self.assertLess(TIERS.index(self.tier(700)), TIERS.index(CFG.squeeze_to))

    def test_every_width_lands_somewhere(self):
        """Nicio lățime, oricât de ciudată, nu trebuie să rămână fără nivel."""
        for width in range(200, 4000, 7):
            self.assertIn(self.tier(width), TIERS)

    def test_tiers_only_ever_loosen_as_the_bar_grows(self):
        """Mai mult loc nu are voie să ducă la un nivel mai strâns."""
        previous = 0
        for width in range(200, 4000, 13):
            current = TIERS.index(self.tier(width))
            self.assertGreaterEqual(current, previous, f"la {width}px nivelul a scăzut")
            previous = current


class TestTiersAndHiding(unittest.TestCase):
    """Nivelurile și ascunderea widget-urilor lucrează pe aceeași măsurătoare."""

    def test_a_narrow_bar_both_tightens_and_hides(self):
        """Strângerea e primul pas, nu singurul: ce nu încape nici așa, dispare."""
        bar = Bar(1084, shrinking(1400), hideable=280)
        self.assertEqual(bar.settle(), CFG.squeeze_to, "s-a strâns")
        order = [("tray", 120, False), ("weather", 90, False), ("ram", 70, False)]
        sides = {"left": (300, []), "right": (800, order)}
        to_hide, _ = plan_bar(budget=1084, fixed=150, sides=sides, hysteresis=CFG.hysteresis)
        self.assertTrue(to_hide, "pe o bară strâmtă ceva tot trebuie să dispară")

    def test_units_are_dropped_from_dense_down(self):
        from core.validation.widgets.yasb.responsive import ResponsiveConfig

        limit = ResponsiveConfig().hide_units_from
        self.assertTrue(at_or_below("dense", limit))
        self.assertTrue(at_or_below("min", limit))
        self.assertFalse(at_or_below("normal", limit), "pe un ecran normal unitățile rămân scrise")


if __name__ == "__main__":
    unittest.main()


class FakeUnit:
    """O etichetă de unitate: „%", „°C", „MHz"."""

    def __init__(self, text: str, hidden: bool = False):
        self.text = text
        self._hidden = hidden

    def isHidden(self) -> bool:  # noqa: N802 - nume Qt
        return self._hidden

    def setVisible(self, visible: bool) -> None:  # noqa: N802 - nume Qt
        self._hidden = not visible


def apply_units(labels, show: bool) -> None:
    """Ce face widget-ul responsive după ce a hotărât."""
    to_hide, to_show = units_to_change(labels, show)
    for label in to_hide:
        setattr(label, UNIT_HIDDEN, True)
        label.setVisible(False)
    for label in to_show:
        setattr(label, UNIT_HIDDEN, False)
        label.setVisible(True)


class TestUnits(unittest.TestCase):
    """
    Unitățile se ascund pe bare strâmte — dar numai ale etichetei care chiar se vede.

    Fiecare widget are două seturi de etichete: cel normal și cel alternativ, pe care îl vezi
    doar dacă dai click. YASB îl ține pe al doilea ascuns. Prima variantă a acestei reguli
    arăta înapoi toate etichetele de unitate, inclusiv pe cele alternative — așa că bara a
    ajuns să scrie „CPU 17% MHz 55°C": procentul de la eticheta normală și MHz de la cea
    alternativă, unul lângă altul.

    Regula e aceeași ca la widget-uri: ascundem orice, dar arătăm înapoi doar ce am ascuns noi.
    """

    def test_a_tight_bar_hides_the_units(self):
        percent, degrees = FakeUnit("%"), FakeUnit("°C")
        apply_units([percent, degrees], show=False)
        self.assertTrue(percent.isHidden())
        self.assertTrue(degrees.isHidden())

    def test_they_come_back_when_there_is_room(self):
        percent = FakeUnit("%")
        apply_units([percent], show=False)
        apply_units([percent], show=True)
        self.assertFalse(percent.isHidden())

    def test_the_alt_label_is_never_revealed(self):
        """Cazul exact din bara ta: MHz și W apăreau lângă procente."""
        percent = FakeUnit("%")
        mhz = FakeUnit("MHz", hidden=True)  # eticheta alternativă, ascunsă de YASB
        watts = FakeUnit("W", hidden=True)
        apply_units([percent, mhz, watts], show=True)
        self.assertFalse(percent.isHidden())
        self.assertTrue(mhz.isHidden(), "MHz a apărut lângă procent")
        self.assertTrue(watts.isHidden(), "W a apărut lângă grade")

    def test_hiding_then_showing_does_not_reveal_the_alt_label_either(self):
        percent = FakeUnit("%")
        mhz = FakeUnit("MHz", hidden=True)
        apply_units([percent, mhz], show=False)
        apply_units([percent, mhz], show=True)
        self.assertFalse(percent.isHidden())
        self.assertTrue(mhz.isHidden())

    def test_repeating_the_same_decision_changes_nothing(self):
        percent = FakeUnit("%")
        for _ in range(5):
            apply_units([percent], show=True)
        self.assertFalse(percent.isHidden())
        for _ in range(5):
            apply_units([percent], show=False)
        self.assertTrue(percent.isHidden())
