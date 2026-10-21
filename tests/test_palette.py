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


class TestVividCandidates(unittest.TestCase):
    """
    Culorile aprinse se numără pe nuanțe, din pixeli neatinși.

    Cuantizarea împarte imaginea după cât loc ocupă fiecare culoare, deci o dungă subțire de
    neon e înghițită de suprafața din jur. Iar micșorarea obișnuită o amestecă cu fundalul.
    """

    def test_the_exact_neon_survives(self):
        from yasb_palette import vivid_candidates

        # 400 de pixeli de neon curat și 60 amestecați cu fundalul, în aceeași felie de nuanță
        colors = [(400, (255, 106, 31)), (60, (182, 79, 28))]
        self.assertEqual(vivid_candidates(colors, 10_000)[0][1], "#ff6a1f")

    def test_the_share_is_the_whole_slice(self):
        from yasb_palette import vivid_candidates

        colors = [(400, (255, 106, 31)), (60, (250, 110, 40))]
        share, _ = vivid_candidates(colors, 10_000)[0]
        self.assertAlmostEqual(share, 0.046, places=3)

    def test_dull_and_dark_pixels_are_ignored(self):
        from yasb_palette import vivid_candidates

        self.assertEqual(vivid_candidates([(9_000, (40, 50, 62))], 10_000), [])  # gri-albăstrui
        self.assertEqual(vivid_candidates([(9_000, (13, 16, 20))], 10_000), [])  # aproape negru

    def test_different_hues_stay_apart(self):
        from yasb_palette import vivid_candidates

        colors = [(300, (255, 106, 31)), (300, (159, 214, 232))]
        self.assertEqual(len(vivid_candidates(colors, 10_000)), 2)

    def test_the_same_pixels_always_give_the_same_answer(self):
        from yasb_palette import vivid_candidates

        colors = [(100, (255, 0, 0)), (100, (0, 255, 0)), (100, (0, 0, 255))]
        first = vivid_candidates(colors, 1_000)
        self.assertEqual(vivid_candidates(list(reversed(colors)), 1_000), first)


def _image(draw):
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (800, 450), (13, 16, 20))
    draw(ImageDraw.Draw(im))
    return im


def _palette(draw):
    import tempfile

    from yasb_palette import build_palette, extract_with_pillow

    path = Path(tempfile.mkdtemp()) / "wallpaper.png"
    _image(draw).save(path)
    data = extract_with_pillow(path)
    return build_palette(data["bg"], data["candidates"])


def _night(d):
    """
    Ca wallpaper-ul lui: noapte, o dungă subțire de neon portocaliu, o lumină rece.

    Dunga are patru pixeli dinadins: atât de subțire încât o micșorare obișnuită o amestecă
    cu negrul din jur și scoate din ea un cărămiziu închis.
    """
    d.rectangle([0, 150, 800, 260], fill=(40, 50, 62))
    d.rectangle([100, 120, 700, 124], fill=(255, 106, 31))
    d.rectangle([150, 300, 650, 316], fill=(159, 214, 232))


try:
    import PIL  # noqa: F401

    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False


@unittest.skipUnless(HAS_PIL, "fără Pillow nu putem citi imagini")
class TestOnRealImages(unittest.TestCase):
    def test_the_neon_reaches_the_bar(self):
        """Accentul trebuie să fie portocaliul din imagine, nu un cărămiziu amestecat."""
        accent = _palette(_night)["accent"]
        hue, _light, sat = hls(accent)
        self.assertLess(abs(hue - hls("#ff6a1f")[0]), 0.02, f"altă nuanță: {accent}")
        self.assertGreater(sat, 0.8, f"accent spălăcit: {accent}")

    def test_the_second_accent_is_the_other_light(self):
        from yasb_palette import hue_distance

        p = _palette(_night)
        self.assertGreaterEqual(hue_distance(hls(p["accent"])[0], hls(p["accent2"])[0]), 40)

    def test_it_stays_readable(self):
        from yasb_palette import contrast

        p = _palette(_night)
        self.assertGreaterEqual(contrast(p["text"], p["bar"]), 7.0)
        self.assertGreaterEqual(contrast(p["accent"], p["bar"]), 4.5)
        self.assertGreaterEqual(contrast(p["sub"], p["bar"]), 4.5)

    def test_the_same_image_gives_the_same_palette(self):
        self.assertEqual(_palette(_night), _palette(_night))

    def test_a_grey_photo_stays_grey(self):
        def grey(d):
            d.rectangle([0, 0, 800, 450], fill=(60, 60, 62))
            d.rectangle([0, 300, 800, 450], fill=(110, 110, 112))

        p = _palette(grey)
        self.assertLess(hls(p["bar"])[2], 0.12, "un wallpaper gri nu trebuie colorat din senin")

    def test_a_warm_photo_gives_a_warm_accent(self):
        def forest(d):
            d.rectangle([0, 0, 800, 450], fill=(24, 42, 30))
            d.rectangle([0, 300, 800, 450], fill=(46, 78, 52))
            d.ellipse([300, 100, 500, 250], fill=(222, 196, 92))

        hue = hls(_palette(forest)["accent"])[0]
        self.assertLess(abs(hue - hls("#dec45c")[0]), 0.03, "soarele galben trebuie să dea accentul")


class TestAmbience(unittest.TestCase):
    """
    Nuanța de ansamblu a imaginii — alta decât accentul.

    Accentul e ce sare în ochi (neonul portocaliu); ansamblul e în ce e scăldată imaginea
    (albastrul-verzui al stației). Fundalul barei trebuie să vină din ansamblu. Până acum
    venea din culoarea cu cel mai mult loc — pe o poză de noapte, negrul — iar negrul n-are
    nuanță, așa că regula cădea pe varianta de rezervă: nuanța accentului. Deci bara ieșea
    maronie sub un wallpaper albastru-verzui.
    """

    TEAL = [(0.30, "#000000"), (0.25, "#204146"), (0.20, "#1f4045"), (0.10, "#4c757b"), (0.02, "#ff6a1f")]

    def test_a_teal_photo_has_a_teal_ambience(self):
        from yasb_palette import ambience

        hue, strength = ambience(self.TEAL)
        self.assertLess(abs(hue - hls("#204146")[0]), 0.05, f"nuanță greșită: {hue * 360:.0f}°")
        self.assertGreater(strength, 0.05)

    def test_a_thin_neon_does_not_set_the_mood(self):
        """Dunga portocalie e accentul, nu atmosfera: 2 % nu are voie să întoarcă bara pe cald."""
        from yasb_palette import ambience

        hue, _ = ambience(self.TEAL)
        self.assertGreater(abs(hue - hls("#ff6a1f")[0]), 0.2)

    def test_grey_has_no_mood(self):
        from yasb_palette import ambience

        _hue, strength = ambience([(0.7, "#2b2b2b"), (0.3, "#777777")])
        self.assertEqual(strength, 0.0)

    def test_hues_are_averaged_around_the_circle(self):
        """Roșu la 350° și roșu la 10° dau roșu, nu verde (media simplă ar da 180°)."""
        from yasb_palette import ambience

        hue, _ = ambience([(0.5, "#ff0066"), (0.5, "#ff6600")])
        self.assertLess(min(hue, 1 - hue), 0.08, f"a ieșit {hue * 360:.0f}°")


@unittest.skipUnless(HAS_PIL, "fără Pillow nu putem citi imagini")
class TestTheBarMatchesThePhoto(unittest.TestCase):
    def test_a_cold_photo_gives_a_cold_bar(self):
        """Bara ia atmosfera pozei, accentul ia neonul: două întrebări, două răspunsuri."""
        from yasb_palette import hue_distance

        p = _palette(_night)
        bar_hue = hls(p["bar"])[0]
        self.assertLess(abs(bar_hue - hls("#28323e")[0]), 0.08, f"bară {p['bar']}")
        self.assertGreater(hue_distance(bar_hue, hls(p["accent"])[0]), 100, "bara a luat nuanța accentului")

    def test_the_bar_is_tinted_enough_to_see(self):
        self.assertGreater(hls(_palette(_night)["bar"])[2], 0.08)

    def test_a_warm_photo_gives_a_warm_bar(self):
        def sunset(d):
            d.rectangle([0, 0, 800, 450], fill=(94, 48, 28))
            d.rectangle([0, 250, 800, 450], fill=(140, 72, 36))
            d.ellipse([350, 80, 450, 180], fill=(255, 214, 120))

        bar_hue = hls(_palette(sunset)["bar"])[0]
        self.assertLess(abs(bar_hue - hls("#8c4824")[0]), 0.06, "o poză caldă trebuie să dea o bară caldă")
