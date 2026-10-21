"""
Bara pe orice ecran: nivelul se alege din spațiul rămas, nu din rezoluție.

Asta e miezul cerinței „să se muleze pe orice monitor, chiar și pe unele pe care nu le ai”.
Dacă nivelul s-ar alege din numărul de pixeli, ar trebui o listă de rezoluții undeva — și
orice ecran din afara listei ar cădea pe lângă. Măsurând locul liber, un monitor mare scalat
la 150 % și un laptop mic ajung singure la același nivel.
"""

import unittest

import stubs

stubs.install()

from core.validation.widgets.yasb.responsive import TIERS, TierThresholds  # noqa: E402
from core.widgets.yasb.responsive import UNIT_HIDDEN, at_or_below, plan, tier_for, units_to_change  # noqa: E402

TH = TierThresholds()


def room_on_one_side(bar_width: int, clock_width: int = 150, margin: int = 16) -> int:
    """Cât rămâne pe o latură: lățimea barei, minus ceasul din mijloc, împărțit la două."""
    return (bar_width - clock_width) // 2 - margin


class TestTiers(unittest.TestCase):
    def test_the_ladder_is_ordered(self):
        self.assertEqual(TIERS, ("min", "dense", "normal", "full"))

    def test_plenty_of_room_means_everything(self):
        self.assertEqual(tier_for(1000, TH), "full")

    def test_exactly_on_a_threshold_counts_as_the_higher_tier(self):
        self.assertEqual(tier_for(TH.full, TH), "full")
        self.assertEqual(tier_for(TH.normal, TH), "normal")
        self.assertEqual(tier_for(TH.dense, TH), "dense")

    def test_one_pixel_below_a_threshold_steps_down(self):
        self.assertEqual(tier_for(TH.full - 1, TH), "normal")
        self.assertEqual(tier_for(TH.normal - 1, TH), "dense")
        self.assertEqual(tier_for(TH.dense - 1, TH), "min")

    def test_no_room_at_all(self):
        self.assertEqual(tier_for(0, TH), "min")
        self.assertEqual(tier_for(-200, TH), "min", "o bară mai îngustă decât ceasul nu trebuie să crape")

    def test_a_rotated_screen_never_goes_above_dense(self):
        """Un ecran rotit are problema unui laptop, oricâți pixeli ar avea pe verticală."""
        self.assertEqual(tier_for(2000, TH, portrait=True), "dense")
        self.assertEqual(tier_for(200, TH, portrait=True), "min", "portretul nu urcă nivelul, doar îl limitează")

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
    """

    def tier(self, bar_width: int, portrait: bool = False) -> str:
        return tier_for(room_on_one_side(bar_width), TH, portrait)

    def test_a_big_monitor_gets_everything(self):
        self.assertEqual(self.tier(2560), "full")
        self.assertEqual(self.tier(3840), "full")

    def test_a_laptop_is_comfortable(self):
        self.assertEqual(self.tier(1920), "full")

    def test_scaling_and_resolution_meet_at_the_same_tier(self):
        scaled_up = self.tier(1536)  # 1920 la 125 %
        native = self.tier(1536)  # un ecran de 1536 la 100 %
        self.assertEqual(scaled_up, native)
        self.assertEqual(scaled_up, "normal")

    def test_a_4k_at_150_percent_is_the_same_as_1440p(self):
        self.assertEqual(self.tier(2560), self.tier(2560))  # 3840 la 150 % = 2560 px logici

    def test_a_small_laptop_tightens_up(self):
        self.assertEqual(self.tier(1366), "normal")

    def test_a_rotated_screen_is_treated_as_tight(self):
        self.assertEqual(self.tier(1080, portrait=True), "dense")

    def test_a_very_narrow_bar_keeps_only_the_essentials(self):
        self.assertEqual(self.tier(700), "min")

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
        room = room_on_one_side(1100)
        self.assertEqual(tier_for(room, TH), "dense")
        order = [("tray", 120, False), ("weather", 90, False), ("ram", 70, False)]
        to_hide, _ = plan(need=500, avail=room, order=order, hysteresis=24)
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
