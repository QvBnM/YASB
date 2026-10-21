"""Deciziile de așezare: ce widget dispare când nu mai e loc, și unde ajung ferestrele maximizate."""

import unittest

import stubs

stubs.install()

from core.widgets.yasb.responsive import plan  # noqa: E402
from core.widgets.yasb.window_fix import (  # noqa: E402
    compute_fix,
    compute_fullscreen_fit,
    covers_monitor,
    is_fullscreen_game,
    reservation_missing,
)


class TestPlan(unittest.TestCase):
    """plan(nevoie, loc, ordine, histerezis) -> (de_ascuns, de_aratat)"""

    def test_nothing_to_do_when_it_fits(self):
        order = [("viz", 40, False), ("media", 200, False)]
        self.assertEqual(plan(300, 500, order, 24), ([], []))

    def test_hides_least_important_first(self):
        order = [("viz", 40, False), ("git", 90, False), ("media", 200, False)]
        to_hide, to_show = plan(600, 500, order, 24)
        self.assertEqual(to_hide, ["viz", "git"])  # 600-40-90 = 470 <= 500, media rămâne
        self.assertEqual(to_show, [])

    def test_stops_as_soon_as_it_fits(self):
        order = [("viz", 150, False), ("git", 90, False)]
        to_hide, _ = plan(600, 500, order, 24)
        self.assertEqual(to_hide, ["viz"])

    def test_brings_back_most_important_first(self):
        order = [("viz", 40, True), ("git", 90, True), ("media", 200, True)]
        _, to_show = plan(100, 500, order, 24)
        self.assertEqual(to_show[0], "media")  # cel mai important din cele ascunse

    def test_never_shows_a_less_important_one_before_a_more_important_one(self):
        # media nu încape, deci nici git și viz nu se întorc, chiar dacă ele ar încăpea
        order = [("viz", 10, True), ("git", 10, True), ("media", 400, True)]
        _, to_show = plan(150, 500, order, 24)
        self.assertEqual(to_show, [])

    def test_hysteresis_keeps_it_from_flickering(self):
        # exact cât trebuie, dar fără rezerva de 24 px: nu îl aducem înapoi
        order = [("viz", 100, True)]
        _, to_show = plan(400, 500, order, 24)
        self.assertEqual(to_show, [])
        _, to_show = plan(400, 525, order, 24)
        self.assertEqual(to_show, ["viz"])

    def test_ignores_zero_width_widgets(self):
        order = [("ghost", 0, False), ("media", 200, False)]
        to_hide, _ = plan(600, 500, order, 24)
        self.assertEqual(to_hide, ["media"])


class TestMaximised(unittest.TestCase):
    """compute_fix: fereastra maximizată trebuie să stea exact în spațiul liber."""

    MONITOR = (0, 0, 1920, 1080)
    WORK = (0, 34, 1920, 1032)  # bară de 34 sus, taskbar de 48 jos

    def test_window_that_already_fits_is_left_alone(self):
        win = frame = (0, 34, 1920, 1032)
        self.assertIsNone(compute_fix(win, frame, self.WORK, self.MONITOR))

    def test_window_sliding_under_the_taskbar_is_moved_back(self):
        # Discord: pus sub bară, dar cu înălțimea ecranului minus taskbar -> iese jos
        frame = (0, 34, 1920, 1080)
        win = frame
        self.assertEqual(compute_fix(win, frame, self.WORK, self.MONITOR), (0, 34, 1920, 1032))

    def test_invisible_resize_borders_are_preserved(self):
        # fereastra reală e cu 8 px mai mare pe fiecare latură decât ce se vede
        frame = (0, 34, 1920, 1080)
        win = (-8, 26, 1928, 1088)
        self.assertEqual(compute_fix(win, frame, self.WORK, self.MONITOR), (-8, 26, 1928, 1040))

    def test_real_fullscreen_is_never_touched(self):
        frame = self.MONITOR
        self.assertIsNone(compute_fix(frame, frame, self.WORK, self.MONITOR))

    def test_tolerance_absorbs_one_pixel_of_rounding(self):
        frame = (0, 33, 1920, 1033)  # 1 px peste, în ambele părți
        self.assertIsNone(compute_fix(frame, frame, self.WORK, self.MONITOR, tolerance=2))


class TestFullscreenFit(unittest.TestCase):
    """compute_fullscreen_fit: fullscreen în browser/player începe sub bară, nu sub ea ascuns."""

    MONITOR = (0, 0, 1920, 1080)
    WORK = (0, 34, 1920, 1032)

    def test_fullscreen_window_starts_below_the_bar(self):
        frame = win = self.MONITOR
        self.assertEqual(compute_fullscreen_fit(win, frame, self.WORK, self.MONITOR), (0, 34, 1920, 1080))

    def test_not_fullscreen_means_nothing_to_do(self):
        frame = win = (100, 100, 800, 600)
        self.assertIsNone(compute_fullscreen_fit(win, frame, self.WORK, self.MONITOR))

    def test_no_bar_on_this_monitor_means_nothing_to_do(self):
        work = (0, 0, 1920, 1032)  # nimic rezervat sus
        frame = win = self.MONITOR
        self.assertIsNone(compute_fullscreen_fit(win, frame, work, self.MONITOR))

    def test_bar_at_the_bottom_is_not_a_top_strip(self):
        work = (0, 0, 1920, 1046)
        frame = win = self.MONITOR
        self.assertIsNone(compute_fullscreen_fit(win, frame, work, self.MONITOR))


class TestBarReservation(unittest.TestCase):
    """reservation_missing: Windows a uitat spațiul rezervat pentru bară?"""

    MONITOR = (0, 0, 1920, 1080)

    def test_space_is_there(self):
        self.assertFalse(reservation_missing("top", 34, (0, 34, 1920, 1032), self.MONITOR))

    def test_space_is_gone(self):
        self.assertTrue(reservation_missing("top", 34, (0, 0, 1920, 1032), self.MONITOR))

    def test_bottom_bar(self):
        self.assertFalse(reservation_missing("bottom", 34, (0, 0, 1920, 1046), self.MONITOR))
        self.assertTrue(reservation_missing("bottom", 34, (0, 0, 1920, 1080), self.MONITOR))

    def test_no_bar_means_nothing_to_guard(self):
        self.assertFalse(reservation_missing("top", 0, (0, 0, 1920, 1080), self.MONITOR))


class TestFullscreenGame(unittest.TestCase):
    """Bara trece în spatele unui joc pe tot ecranul, dar nu în spatele Start sau al desktopului."""

    MONITOR = (0, 0, 1920, 1080)
    FULL = (0, 0, 1920, 1080)
    KEEP: set[str] = {"chrome.exe"}

    def test_a_game_hides_the_bar(self):
        self.assertTrue(is_fullscreen_game("eldenring.exe", "UnrealWindow", False, self.FULL, self.MONITOR, self.KEEP))

    def test_the_desktop_does_not(self):
        self.assertFalse(is_fullscreen_game("explorer.exe", "WorkerW", False, self.FULL, self.MONITOR, self.KEEP))

    def test_the_start_menu_does_not(self):
        self.assertFalse(
            is_fullscreen_game(
                "StartMenuExperienceHost.exe", "Windows.UI.Core.CoreWindow", False, self.FULL, self.MONITOR, self.KEEP
            )
        )

    def test_our_own_window_does_not(self):
        # bara însăși e fullscreen pe lățime: nu are voie să se ascundă în spatele ei
        self.assertFalse(is_fullscreen_game("python.exe", "Qt", True, self.FULL, self.MONITOR, self.KEEP))

    def test_a_browser_in_fullscreen_keeps_the_bar(self):
        # chrome e în fullscreen_fit: îl potrivim sub bară, nu ascundem bara
        self.assertFalse(is_fullscreen_game("chrome.exe", "Chrome_WidgetWin_1", False, self.FULL, self.MONITOR, self.KEEP))

    def test_a_window_that_does_not_cover_the_monitor_does_not(self):
        self.assertFalse(
            is_fullscreen_game("eldenring.exe", "UnrealWindow", False, (0, 0, 1280, 720), self.MONITOR, self.KEEP)
        )

    def test_covers_monitor_tolerance(self):
        self.assertTrue(covers_monitor((1, 1, 1919, 1079), self.MONITOR, tolerance=2))
        self.assertFalse(covers_monitor((10, 10, 1910, 1070), self.MONITOR, tolerance=2))


if __name__ == "__main__":
    unittest.main()
