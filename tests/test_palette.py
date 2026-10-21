"""
Alegerea culorii de accent din imaginea de fundal.

Scriptul care colorează bara e `tools/yasb_palette.py`. Alegea accentul numai după cât de
colorată e o culoare, fără să conteze deloc cât loc ocupă în imagine: câștiga cel mai viu
petic, chiar dacă erau zece pixeli dintr-un logo sau din zgomotul unui JPEG. Iar ordinea
pleca de la o mulțime, a cărei ordine diferă de la o pornire la alta — așa că aceeași
imagine putea da alt accent după o repornire.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from yasb_palette import MIN_SHARE, build_palette, hls, rank_candidates, vividness

# O imagine ca wallpaper-ul lui: aproape toată închisă, cu o dungă subțire de neon portocaliu
# și una de lumină rece. Suprafața mare e un gri-albăstrui spălăcit.
NIGHT = [
    (0.74, "#0d1014"),  # negru: prea închis ca să fie accent
    (0.17, "#4a5560"),  # gri-albăstrui spălăcit: mult, dar fără culoare
    (0.05, "#9fd6e8"),  # lumina rece de sub copertină
    (0.03, "#ff6a1f"),  # neonul portocaliu
    (0.002, "#1fff8a"),  # un pixel-doi de verde: zgomot
]


class TestVividness(unittest.TestCase):
    def test_grey_is_not_a_colour(self):
        self.assertEqual(vividness("#808080"), 0.0)

    def test_near_black_and_near_white_are_out(self):
        self.assertEqual(vividness("#0d1014"), 0.0)
        self.assertEqual(vividness("#f8fbff"), 0.0)

    def test_a_neon_beats_a_washed_out_colour(self):
        self.assertGreater(vividness("#ff6a1f"), vividness("#4a5560"))


class TestRanking(unittest.TestCase):
    def test_a_thin_neon_wins_over_a_large_dull_area(self):
        """17 % de gri spălăcit nu trebuie să bată 3 % de neon: nu e o culoare a imaginii."""
        self.assertEqual(rank_candidates(NIGHT)[0], "#ff6a1f")

    def test_a_handful_of_pixels_never_wins(self):
        """Verdele acela e zgomot. Înainte câștiga: era cel mai viu din imagine."""
        self.assertNotIn("#1fff8a", rank_candidates(NIGHT))

    def test_a_colour_of_the_image_beats_a_more_vivid_speck(self):
        """
        Miezul schimbării: între două culori adevărate, contează și cât loc ocupă.

        Cărămiziul acoperă 40 % din imagine; roșul aprins, 1 %. Înainte câștiga roșul, fiindcă
        era mai viu — și ieșea un accent pe care nu-l regăseai nicăieri pe ecran.
        """
        most_of_the_image, a_speck = "#d94f2a", "#ff1a1a"
        ranked = rank_candidates([(0.40, most_of_the_image), (0.012, a_speck)])
        self.assertEqual(ranked[0], most_of_the_image)

    def test_but_vividness_still_decides_between_equals(self):
        """La fel de prezente, câștigă culoarea, nu spălăceala."""
        ranked = rank_candidates([(0.30, "#8a7f6e"), (0.30, "#ff6a1f")])
        self.assertEqual(ranked[0], "#ff6a1f")

    def test_the_same_image_always_gives_the_same_accent(self):
        """
        Două culori la egalitate nu au voie să-și schimbe locul între porniri.

        `sorted(set(...))` pleca de la o mulțime: ordinea ei diferă de la un proces la altul.
        """
        tie = [(0.20, "#ff0000"), (0.20, "#00ff00"), (0.20, "#0000ff")]
        # la egalitate, ordinea e cea a numelui culorii: aceeași de fiecare dată, pe orice pornire
        self.assertEqual(rank_candidates(tie), ["#0000ff", "#00ff00", "#ff0000"])
        self.assertEqual(rank_candidates(list(reversed(tie))), ["#0000ff", "#00ff00", "#ff0000"])

    def test_a_grey_wallpaper_has_no_accent(self):
        self.assertEqual(rank_candidates([(0.8, "#2b2b2b"), (0.2, "#777777")]), [])

    def test_the_noise_floor(self):
        just_under = [(MIN_SHARE / 2, "#ff6a1f")]
        just_over = [(MIN_SHARE * 2, "#ff6a1f")]
        self.assertEqual(rank_candidates(just_under), [])
        self.assertEqual(rank_candidates(just_over), ["#ff6a1f"])


class TestPalette(unittest.TestCase):
    def test_the_bar_takes_the_accent_from_the_image(self):
        p = build_palette("#0d1014", NIGHT)
        self.assertAlmostEqual(hls(p["accent"])[0], hls("#ff6a1f")[0], places=2)

    def test_the_second_accent_is_a_different_colour(self):
        from yasb_palette import hue_distance

        p = build_palette("#0d1014", NIGHT)
        self.assertGreaterEqual(hue_distance(hls(p["accent"])[0], hls(p["accent2"])[0]), 40)

    def test_a_grey_wallpaper_stays_neutral(self):
        p = build_palette("#2b2b2b", [(0.8, "#2b2b2b"), (0.2, "#777777")])
        self.assertLess(hls(p["bar"])[2], 0.1, "un fundal gri nu trebuie colorat din senin")


if __name__ == "__main__":
    unittest.main()
