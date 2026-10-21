"""Praguri de culoare, calculele de contrast din paletă, și textele în română."""

import unittest
from datetime import date

import stubs

stubs.install()

from core.widgets.yasb.call_status import format_elapsed  # noqa: E402
from core.widgets.yasb.mint_common import (  # noqa: E402
    FALLBACK_PALETTE,
    contrast,
    ensure_contrast,
    foreground,
    luminance,
    mic_users,
    mix,
    parse_palette,
    process_name,
    ro_day_month,
    ro_days,
    running_process_names,
    ttl_cache,
)
from core.widgets.yasb.mint_thresholds import evaluate, with_level  # noqa: E402
from core.widgets.yasb.ui_polish import format_range, merge_holidays  # noqa: E402
from core.validation.widgets.yasb.mint_thresholds import ThresholdRule  # noqa: E402


def rule(**kw):
    return ThresholdRule(**{"widget": "cpu", **kw})


class TestThresholds(unittest.TestCase):
    def test_below_warn_is_plain(self):
        self.assertIsNone(evaluate("42", [rule(warn=85, crit=95)]))

    def test_over_warn(self):
        self.assertEqual(evaluate("86", [rule(warn=85, crit=95)]), "warn")

    def test_over_crit(self):
        self.assertEqual(evaluate("96", [rule(warn=85, crit=95)]), "crit")

    def test_exactly_on_the_threshold_counts(self):
        self.assertEqual(evaluate("85", [rule(warn=85, crit=95)]), "warn")

    def test_below_rule_is_inverted(self):
        # FPS: mic = rău
        fps = rule(warn=45, crit=30, below=True)
        self.assertIsNone(evaluate("60", [fps]))
        self.assertEqual(evaluate("40", [fps]), "warn")
        self.assertEqual(evaluate("25", [fps]), "crit")

    def test_crit_wins_over_warn(self):
        self.assertEqual(evaluate("99", [rule(warn=85, crit=95), rule(warn=10, crit=1000)]), "crit")

    def test_comma_decimal_is_read(self):
        self.assertEqual(evaluate("86,5", [rule(warn=85, crit=95)]), "warn")

    def test_text_without_a_number_is_ignored(self):
        self.assertIsNone(evaluate("--", [rule(warn=85, crit=95)]))
        self.assertIsNone(evaluate("", [rule(warn=85, crit=95)]))

    def test_class_token_is_replaced_not_stacked(self):
        self.assertEqual(with_level("label warn", "crit"), "label crit")
        self.assertEqual(with_level("label crit", None), "label")
        self.assertEqual(with_level("label", "warn"), "label warn")

    def test_class_token_keeps_other_classes(self):
        self.assertEqual(with_level("label unit warn", "crit"), "label unit crit")


class TestContrast(unittest.TestCase):
    """Regula pentru care bara rămâne citibilă pe orice wallpaper."""

    def test_known_values(self):
        self.assertAlmostEqual(contrast("#ffffff", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(contrast("#ffffff", "#ffffff"), 1.0, places=3)

    def test_order_does_not_matter(self):
        self.assertAlmostEqual(contrast("#7dd9c7", "#101716"), contrast("#101716", "#7dd9c7"), places=6)

    def test_ensure_contrast_reaches_the_target_on_a_dark_background(self):
        colour, _moved = ensure_contrast("#1a3b35", "#101716", 4.5)
        self.assertGreaterEqual(contrast(colour, "#101716"), 4.5)

    def test_ensure_contrast_reaches_the_target_on_a_light_background(self):
        colour, _moved = ensure_contrast("#d8f0ea", "#f2f5f4", 4.5)
        self.assertGreaterEqual(contrast(colour, "#f2f5f4"), 4.5)

    def test_a_colour_that_already_passes_is_untouched(self):
        colour, moved = ensure_contrast("#e6eceb", "#101716", 4.5)
        self.assertEqual(colour, "#e6eceb")
        self.assertEqual(moved, 0.0)

    def test_the_shipped_palette_is_readable(self):
        p = FALLBACK_PALETTE
        self.assertGreaterEqual(contrast(p["text"], p["bar"]), 7.0)
        self.assertGreaterEqual(contrast(p["sub"], p["bar"]), 4.5)
        self.assertGreaterEqual(contrast(p["accent"], p["bar"]), 4.5)
        self.assertGreaterEqual(contrast(p["danger"], p["bar"]), 4.5)
        self.assertGreaterEqual(contrast(p["warn"], p["bar"]), 4.5)

    def test_luminance_is_ordered(self):
        self.assertLess(luminance("#000000"), luminance("#7f7f7f"))
        self.assertLess(luminance("#7f7f7f"), luminance("#ffffff"))

    def test_mix_endpoints(self):
        self.assertEqual(mix("#000000", "#ffffff", 0.0), "#000000")
        self.assertEqual(mix("#000000", "#ffffff", 1.0), "#ffffff")


class TestPaletteFile(unittest.TestCase):
    def test_variables_are_read(self):
        css = ":root {\n  --bar: #101716;\n  --accent: #7DD9C7;\n}"
        p = parse_palette(css)
        self.assertEqual(p["bar"], "#101716")
        self.assertEqual(p["accent"], "#7dd9c7")  # normalizat la litere mici

    def test_missing_variables_fall_back(self):
        p = parse_palette(":root { --bar: #000000; }")
        self.assertEqual(p["text"], FALLBACK_PALETTE["text"])

    def test_warn_is_always_present(self):
        self.assertIn("warn", parse_palette(""))

    def test_a_broken_file_does_not_crash(self):
        p = parse_palette("nu e css deloc {{{")
        self.assertEqual(p, dict(FALLBACK_PALETTE))


class TestSharedWork(unittest.TestCase):
    """
    Munca se face o singura data, nu o data pe monitor.

    Exista cate o bara pe fiecare ecran, iar widget-urile invizibile traiesc in fiecare dintre
    ele. Pe trei monitoare se citea de trei ori fereastra activa, de trei ori lista proceselor,
    de trei ori microfonul — desi raspunsul e identic.
    """

    def test_three_bars_ask_once(self):
        calls = []

        @ttl_cache(10_000)
        def sample():
            calls.append(1)
            return "fereastra activa"

        results = [sample() for _ in range(3)]  # trei bare, acelasi moment
        self.assertEqual(results, ["fereastra activa"] * 3)
        self.assertEqual(len(calls), 1, "munca s-a facut o data pentru fiecare monitor")

    def test_an_expired_answer_is_read_again(self):
        calls = []

        @ttl_cache(0)
        def sample():
            calls.append(1)
            return len(calls)

        sample()
        sample()
        self.assertEqual(len(calls), 2, "dupa ce a expirat, trebuie citit din nou")

    def test_different_arguments_are_not_mixed_up(self):
        seen = []

        @ttl_cache(10_000)
        def sample(which):
            seen.append(which)
            return which.upper()

        self.assertEqual(sample("microfon"), "MICROFON")
        self.assertEqual(sample("retea"), "RETEA")
        self.assertEqual(seen, ["microfon", "retea"])

    def test_the_answer_can_be_thrown_away(self):
        calls = []

        @ttl_cache(10_000)
        def sample():
            calls.append(1)
            return len(calls)

        sample()
        sample.cache_clear()
        sample()
        self.assertEqual(len(calls), 2)

    def test_the_shared_readers_are_actually_shared(self):
        """Daca cineva scoate memoria de pe ele, pe mai multe monitoare munca se dubleaza iar."""
        for reader in (foreground, running_process_names, mic_users):
            self.assertTrue(
                hasattr(reader, "cache_clear"),
                f"{reader.__name__} nu mai tine minte raspunsul: munca se face iar pe fiecare bara",
            )


class TestWithoutWindows(unittest.TestCase):
    """
    Citirea proceselor se face acum direct din Windows, fara psutil.

    Setup-ul doar incerca sa instaleze psutil si mergea mai departe cu un avertisment daca nu
    reusea. Fara el, numele ferestrei active ramanea mereu gol, deci modurile automate, branch-ul
    git si FPS-ul taceau fara nicio eroare. Aici verificam doar ca, in lipsa Windows-ului,
    raspund gol in loc sa crape — partea care chiar citeste procese se vede pe Windows.
    """

    def test_process_name_answers_empty(self):
        self.assertEqual(process_name(1234), "")

    def test_process_name_of_nothing(self):
        self.assertEqual(process_name(0), "")

    def test_the_process_list_is_empty_not_a_crash(self):
        self.assertEqual(running_process_names(), set())

    def test_the_foreground_window_is_simply_unknown(self):
        fg = foreground()
        self.assertEqual(fg.exe, "")
        self.assertEqual(fg.hwnd, 0)
        self.assertFalse(fg.fullscreen)


class TestRomanian(unittest.TestCase):
    def test_days(self):
        self.assertEqual(ro_days(0), "azi")
        self.assertEqual(ro_days(1), "mâine")
        self.assertEqual(ro_days(3), "3 zile")
        self.assertEqual(ro_days(19), "19 zile")
        self.assertEqual(ro_days(20), "20 de zile")
        self.assertEqual(ro_days(101), "101 zile")

    def test_day_and_month(self):
        self.assertEqual(ro_day_month(date(2026, 1, 7)), "7 ian")
        self.assertEqual(ro_day_month(date(2026, 12, 25)), "25 dec")

    def test_elapsed(self):
        self.assertEqual(format_elapsed(0), "0:00")
        self.assertEqual(format_elapsed(72), "1:12")
        self.assertEqual(format_elapsed(3661), "1:01:01")


class TestHolidays(unittest.TestCase):
    def test_consecutive_days_become_one_range(self):
        items = [(date(2026, 12, 25), "Crăciunul"), (date(2026, 12, 26), "Crăciunul")]
        self.assertEqual(merge_holidays(items), [(date(2026, 12, 25), date(2026, 12, 26), "Crăciunul")])

    def test_different_names_stay_apart(self):
        items = [(date(2026, 12, 25), "Crăciunul"), (date(2026, 12, 26), "A doua zi")]
        self.assertEqual(len(merge_holidays(items)), 2)

    def test_a_gap_breaks_the_range(self):
        items = [(date(2026, 5, 1), "Paștele"), (date(2026, 5, 3), "Paștele")]
        self.assertEqual(len(merge_holidays(items)), 2)

    def test_range_text(self):
        self.assertEqual(format_range(date(2026, 12, 25), date(2026, 12, 25)), "25 dec")
        self.assertEqual(format_range(date(2026, 12, 25), date(2026, 12, 26)), "25–26 dec")
        self.assertEqual(format_range(date(2026, 4, 30), date(2026, 5, 1)), "30 apr – 1 mai")


if __name__ == "__main__":
    unittest.main()


class TestMediaButtons(unittest.TestCase):
    """
    În bară rămâne doar play/pauza; „înapoi" și „înainte" ocupau loc degeaba.

    YASB le face mereu pe toate trei și nu are setare pentru asta, iar din stiluri nu se
    poate: Qt nu cunoaște „display: none". Deci le ascundem din cod, o singură dată.
    """

    class FakeButton:
        def __init__(self):
            self.hidden = False

        def setVisible(self, visible):  # noqa: N802 - nume Qt
            self.hidden = not visible

    class FakeMedia:
        def __init__(self, prev, nxt):
            self._prev_label = prev
            self._next_label = nxt

    def test_it_finds_the_two_buttons(self):
        from core.widgets.yasb.ui_polish import skip_buttons

        prev, nxt = self.FakeButton(), self.FakeButton()
        self.assertEqual(skip_buttons(self.FakeMedia(prev, nxt)), [prev, nxt])

    def test_a_widget_without_them_is_left_alone(self):
        from core.widgets.yasb.ui_polish import skip_buttons

        self.assertEqual(skip_buttons(object()), [])

    def test_the_play_button_is_never_touched(self):
        from core.widgets.yasb.ui_polish import skip_buttons

        media = self.FakeMedia(self.FakeButton(), self.FakeButton())
        media._play_label = self.FakeButton()
        self.assertNotIn(media._play_label, skip_buttons(media))

    def test_once_hidden_we_do_not_come_back(self):
        """A doua trecere nu mai are ce face: altfel ne-am bate cu widget-ul la fiecare pornire."""
        from core.widgets.yasb.ui_polish import SKIP_HIDDEN, to_trim

        media = self.FakeMedia(self.FakeButton(), self.FakeButton())
        first = to_trim([media])
        self.assertEqual(len(first), 2)
        for button in first:
            setattr(button, SKIP_HIDDEN, True)
        self.assertEqual(to_trim([media]), [])
