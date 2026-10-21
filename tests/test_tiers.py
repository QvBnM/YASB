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
from core.widgets.yasb.responsive import at_or_below, plan, tier_for  # noqa: E402

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
