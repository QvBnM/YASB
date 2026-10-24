"""Deciziile de așezare: ce widget dispare când nu mai e loc, și unde ajung ferestrele maximizate."""

import unittest

import stubs

stubs.install()

from core.validation.widgets.yasb.responsive import ResponsiveConfig  # noqa: E402
from core.widgets.yasb.responsive import (  # noqa: E402
    LAST_WIDTH,
    learned_width,
    ResponsiveWidget,
    plan_bar,
    settled,
    still_hidden,
)
from core.widgets.yasb.window_fix import (  # noqa: E402
    GUARD_GIVE_UP,
    compute_fix,
    keeps_undoing,
    keeps_refusing,
    compute_fullscreen_fit,
    covers_monitor,
    is_fullscreen_game,
    mine_to_fix,
    reservation_missing,
    screen_alive,
)


def one_side(need, order):
    """O bară cu widget-uri de ascuns doar pe dreapta."""
    return {"right": (need, order)}


class TestPlanBar(unittest.TestCase):
    """plan_bar(loc, cât cere mijlocul, laturile, histerezis) -> (de_ascuns, de_arătat)"""

    def test_nothing_to_do_when_it_fits(self):
        order = [("viz", 40, False), ("media", 200, False)]
        self.assertEqual(plan_bar(1000, 200, one_side(300, order), 24), ([], []))

    def test_hides_least_important_first(self):
        order = [("viz", 40, False), ("git", 90, False), ("media", 200, False)]
        to_hide, to_show = plan_bar(500, 0, one_side(600, order), 24)
        self.assertEqual(to_hide, ["viz", "git"])  # 600-40-90 = 470 <= 500, media rămâne
        self.assertEqual(to_show, [])

    def test_stops_as_soon_as_it_fits(self):
        order = [("viz", 150, False), ("git", 90, False)]
        to_hide, _ = plan_bar(500, 0, one_side(600, order), 24)
        self.assertEqual(to_hide, ["viz"])

    def test_the_middle_counts_too(self):
        order = [("viz", 150, False)]
        self.assertEqual(plan_bar(500, 0, one_side(400, order), 24)[0], [])
        self.assertEqual(plan_bar(500, 200, one_side(400, order), 24)[0], ["viz"])

    def test_brings_back_most_important_first(self):
        order = [("viz", 40, True), ("git", 90, True), ("media", 200, True)]
        _, to_show = plan_bar(500, 0, one_side(100, order), 24)
        self.assertEqual(to_show, ["media"])  # cel mai important din cele ascunse

    def test_only_one_comes_back_per_measurement(self):
        """Următorul se măsoară din nou: altfel se întoarce un val întreg care nu încape."""
        order = [("viz", 10, True), ("git", 10, True)]
        _, to_show = plan_bar(500, 0, one_side(0, order), 24)
        self.assertEqual(len(to_show), 1)

    def test_never_shows_a_less_important_one_before_a_more_important_one(self):
        # media nu încape, deci nici git și viz nu se întorc, chiar dacă ele ar încăpea
        order = [("viz", 10, True), ("git", 10, True), ("media", 400, True)]
        _, to_show = plan_bar(500, 0, one_side(150, order), 24)
        self.assertEqual(to_show, [])

    def test_hysteresis_keeps_it_from_flickering(self):
        # exact cât trebuie, dar fără rezerva de 24 px: nu îl aducem înapoi
        order = [("viz", 100, True)]
        _, to_show = plan_bar(500, 0, one_side(400, order), 24)
        self.assertEqual(to_show, [])
        _, to_show = plan_bar(525, 0, one_side(400, order), 24)
        self.assertEqual(to_show, ["viz"])

    def test_ignores_zero_width_widgets(self):
        order = [("ghost", 0, False), ("media", 200, False)]
        to_hide, _ = plan_bar(500, 0, one_side(600, order), 24)
        self.assertEqual(to_hide, ["media"])

    def test_it_hides_from_the_side_that_asks_for_the_most(self):
        """Nu mai împărțim bara în două jumătăți egale: scurtăm partea încărcată."""
        sides = {
            "left": (120, [("viz", 60, False)]),
            "right": (700, [("wallpaper", 40, False), ("gpu", 90, False)]),
        }
        to_hide, _ = plan_bar(800, 0, sides, 24)
        self.assertEqual(to_hide, ["wallpaper"])  # 700-40 = 660; 660+120 = 780 <= 800


class TestTheBarThatFitsIsLeftAlone(unittest.TestCase):
    """
    Cazul din bara lui, 1536 px: partea dreaptă cerea mai mult decât jumătatea ei, dar bara
    întreagă încăpea. Socoteala pe jumătăți ascundea șase widget-uri degeaba.
    """

    SIDES = {
        "left": (330, [("viz", 60, False), ("media", 140, False)]),
        "right": (
            760,
            [
                ("wallpaper", 34, False),
                ("vram", 70, False),
                ("gpu", 76, False),
                ("net_group", 110, False),
                ("weather", 90, False),
                ("ram", 70, False),
            ],
        ),
    }

    def test_nothing_is_hidden_when_the_whole_bar_fits(self):
        # 330 + 380 (mijloc) + 760 = 1470 <= 1520
        to_hide, to_show = plan_bar(1520, 380, self.SIDES, 24)
        self.assertEqual(to_hide, [], "bara încăpea, dar tot a ascuns ceva")
        self.assertEqual(to_show, [])

    def test_a_narrower_bar_still_hides_only_what_is_needed(self):
        to_hide, _ = plan_bar(1400, 380, self.SIDES, 24)
        self.assertEqual(to_hide, ["wallpaper", "vram"])  # 70+34 = 104, exact cât lipsea


class TestNoFlicker(unittest.TestCase):
    """
    Palpăirea din jurnal: „hidden ['ram']" și „shown ['ram']" la fiecare secundă.

    Cauza nu era regula, ci cifra: la ascundere scădeam lățimea reală, iar la întoarcere
    socoteam sizeHint-ul, mai mic. Deci „încape" era mereu adevărat după ascundere, iar
    „nu încape" mereu adevărat după arătare. Aici verificăm că aceeași lățime, folosită în
    ambele părți, nu mai poate oscila.
    """

    def test_hiding_then_measuring_again_does_not_bring_it_back(self):
        need, width = 700, 120
        to_hide, _ = plan_bar(640, 0, one_side(need, [("ram", width, False)]), 24)
        self.assertEqual(to_hide, ["ram"])
        # a doua măsurătoare, cu widget-ul ascuns și aceeași lățime ținută minte
        _, to_show = plan_bar(640, 0, one_side(need - width, [("ram", width, True)]), 24)
        self.assertEqual(to_show, [], "l-a adus înapoi în locul din care tocmai l-a scos")

    def test_a_smaller_remembered_width_would_oscillate(self):
        """Dovada că cifra conta: cu sizeHint-ul (mai mic) ciclul începe imediat."""
        need, real, hint = 700, 120, 30
        _, to_show = plan_bar(640, 0, one_side(need - real, [("ram", hint, True)]), 24)
        self.assertEqual(to_show, ["ram"])


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
        # chrome scris anume în fullscreen_fit: îl potrivim sub bară, nu ascundem bara
        self.assertFalse(is_fullscreen_game("chrome.exe", "Chrome_WidgetWin_1", False, self.FULL, self.MONITOR, self.KEEP))

    def test_by_default_fullscreen_means_fullscreen(self):
        """
        Fără nicio listă, orice fereastră pe tot ecranul trece peste bară.

        Înainte, browserele erau în listă: le mutam fereastra sub bară. Chrome și-o punea
        înapoi imediat, noi reîncercam de trei ori la fiecare zece secunde, ore întregi —
        iar pe ecran rămânea tot ecranul acoperit, cu bara deasupra lui. Adică exact ce nu voiai.
        """
        for app in ("chrome.exe", "vlc.exe", "mpv.exe"):
            self.assertTrue(
                is_fullscreen_game(app, "Chrome_WidgetWin_1", False, self.FULL, self.MONITOR, set()),
                f"{app} pe tot ecranul ar trebui să treacă peste bară",
            )

    def test_the_default_list_is_empty(self):
        from core.validation.widgets.yasb.window_fix import WindowFixConfig

        self.assertEqual(WindowFixConfig().fullscreen_fit, [])

    def test_a_window_that_does_not_cover_the_monitor_does_not(self):
        self.assertFalse(
            is_fullscreen_game("eldenring.exe", "UnrealWindow", False, (0, 0, 1280, 720), self.MONITOR, self.KEEP)
        )

    def test_a_capture_overlay_does_not_hide_the_bar(self):
        """
        Snipping Tool acoperă ecranul, dar nu e un joc.

        În jurnal a trimis bara în spate și a adus-o înapoi de 35 de ori, episoade de la 0,8
        la 11 secunde. Suprafața pe care tragi dreptunghiul e deja o poză a ecranului, cu bara
        în ea: ascunsul barei nu schimbă ce iese din captură, doar clipește.
        """
        from core.validation.widgets.yasb.window_fix import WindowFixConfig

        keep = {p.lower() for p in WindowFixConfig().keep_bar_over}
        for app in ("SnippingTool.exe", "ScreenClippingHost.exe", "GameBar.exe"):
            self.assertFalse(
                is_fullscreen_game(app, "Windows.UI.Composition", False, self.FULL, self.MONITOR, keep),
                f"{app} nu ar trebui sa trimita bara in spate",
            )

    def test_a_game_still_hides_it_with_that_list(self):
        from core.validation.widgets.yasb.window_fix import WindowFixConfig

        keep = {p.lower() for p in WindowFixConfig().keep_bar_over}
        for app in ("DyingLightGame.exe", "cs2.exe", "3DMarkTimeSpy.exe"):
            self.assertTrue(
                is_fullscreen_game(app, "UnrealWindow", False, self.FULL, self.MONITOR, keep),
                f"{app} pe tot ecranul ar trebui sa treaca peste bara",
            )

    def test_the_names_are_matched_whatever_the_case(self):
        keep = {"snippingtool.exe"}
        self.assertFalse(is_fullscreen_game("SnippingTool.exe", "Qt", False, self.FULL, self.MONITOR, keep))

    def test_covers_monitor_tolerance(self):
        self.assertTrue(covers_monitor((1, 1, 1919, 1079), self.MONITOR, tolerance=2))
        self.assertFalse(covers_monitor((10, 10, 1910, 1070), self.MONITOR, tolerance=2))


class TestGivingUp(unittest.TestCase):
    """
    O aplicație care își pune fereastra la loc nu trebuie urmărită la nesfârșit.

    În jurnal se vedea Chrome corectat de trei ori la fiecare zece secunde, ore întregi,
    fără niciun efect pe ecran.
    """

    def test_a_couple_of_tries_are_fine(self):
        self.assertFalse(keeps_undoing([1.0, 2.0]))

    def test_the_third_time_we_stop(self):
        self.assertTrue(keeps_undoing([1.0, 2.0, 3.0]))

    def test_a_window_we_never_touched(self):
        self.assertFalse(keeps_undoing([]))


class TestGivingUpOnWindows(unittest.TestCase):
    """
    Nici spațiul rezervat barei nu se cere la nesfârșit.

    În jurnal se vede o singură zonă de lucru, (0, 0, 2560, 1392) pe un monitor de 1440,
    pentru care bara s-a reînregistrat din minut în minut de la 19:41 până la sfârșitul
    jurnalului: 100 de încercări, 100 de rânduri identice, niciun efect.
    """

    def test_the_first_tries_are_worth_it(self):
        self.assertFalse(keeps_refusing(0))
        self.assertFalse(keeps_refusing(GUARD_GIVE_UP - 1))

    def test_after_enough_tries_we_stop(self):
        self.assertTrue(keeps_refusing(GUARD_GIVE_UP))
        self.assertTrue(keeps_refusing(100))

    def test_the_whole_log_would_cost_a_handful_of_tries(self):
        """Socoteala pazei: aceeași zonă de lucru, oricât de des măsurată, se încearcă de GUARD_GIVE_UP ori."""
        monitor = (0, 0, 2560, 1440)
        lost = (0, 0, 2560, 1392)  # doar taskbar-ul, nimic pentru bară
        fails, area, tries, warnings = 0, None, 0, 0
        for work in [lost] * 100:
            if not reservation_missing("top", 34, work, monitor):
                fails, area = 0, None
                continue
            if area != (work, monitor):
                area, fails = (work, monitor), 0
            if keeps_refusing(fails):
                continue
            fails += 1
            tries += 1
            warnings += fails == 1
        self.assertEqual(tries, GUARD_GIVE_UP)
        self.assertEqual(warnings, 1)

    def test_a_new_work_area_is_a_new_chance(self):
        """Un program iese din fullscreen, taskbar-ul revine: situație nouă, se încearcă iar."""
        monitor = (0, 0, 2560, 1440)
        fails, area, tries = GUARD_GIVE_UP, ((0, 0, 2560, 1392), monitor), 0
        for work in ((0, 0, 2560, 1440), (0, 0, 2560, 1392)):
            if area != (work, monitor):
                area, fails = (work, monitor), 0
            if not keeps_refusing(fails):
                fails += 1
                tries += 1
        self.assertEqual(tries, 2)

    def test_the_bar_comes_back_and_the_count_is_cleared(self):
        monitor = (0, 0, 2560, 1440)
        self.assertFalse(reservation_missing("top", 34, (0, 34, 2560, 1392), monitor))


class TestAScreenQtDeleted(unittest.TestCase):
    """
    La schimbarea monitoarelor, paza ajungea la un ecran pe care Qt îl ștersese.

    În jurnal, la 09:49:37: „RuntimeError: wrapped C/C++ object of type QScreen has been
    deleted”, chiar după „Screens updated. Re-initialising all bars”.
    """

    class Alive:
        def devicePixelRatio(self):  # noqa: N802 — numele vine din Qt (QScreen)
            return 1.5

    class Deleted:
        def devicePixelRatio(self):  # noqa: N802 — numele vine din Qt (QScreen)
            raise RuntimeError("wrapped C/C++ object of type QScreen has been deleted")

    def test_a_real_screen_is_used(self):
        self.assertTrue(screen_alive(self.Alive()))

    def test_a_deleted_screen_is_left_alone(self):
        self.assertFalse(screen_alive(self.Deleted()))

    def test_no_screen_at_all(self):
        self.assertFalse(screen_alive(None))


class TestOneWindowOneBar(unittest.TestCase):
    """
    O fereastră o corectează doar bara de pe monitorul ei.

    Cu `screens: ["*"]` sunt trei bare, fiecare cu propriul window_fix. În jurnal
    (10-24, 10:52:40) se vede aceeași fereastră a lui „nvidia app" mutată de nouă ori
    într-o secundă, apoi trei rânduri „nu mai incerc" în loc de unul: pragul de renunțare
    ajungea de trei ori mai mare decât cel din cod.
    """

    def test_my_monitor_my_window(self):
        self.assertTrue(mine_to_fix(7, 7))

    def test_another_monitor_is_another_bar_s_job(self):
        self.assertFalse(mine_to_fix(7, 9))

    def test_an_unknown_monitor_changes_nothing(self):
        # fără un monitor cunoscut ne purtăm ca înainte: corectăm, nu refuzăm
        self.assertTrue(mine_to_fix(0, 9))
        self.assertTrue(mine_to_fix(7, 0))

    def test_three_bars_correct_a_window_once(self):
        bars = (11, 22, 33)  # trei bare, trei monitoare
        window = 22
        self.assertEqual(sum(mine_to_fix(window, bar) for bar in bars), 1)



if __name__ == "__main__":
    unittest.main()


class FakeSize:
    def __init__(self, w):
        self._w = w

    def width(self):
        return self._w


class FakeWidget:
    """Un widget cât îi trebuie lui `_width_of`: o lățime reală și un sizeHint diferit."""

    def __init__(self, real: int, hint: int):
        self._real = real
        self._hint = hint

    def width(self) -> int:
        return self._real

    def layout(self):
        return None

    def sizeHint(self):  # noqa: N802 - nume Qt
        return FakeSize(self._hint)


class TestWidthMemory(unittest.TestCase):
    """
    Lățimea cu care socotim trebuie să fie aceeași la ascundere și la întoarcere.

    Ascuns, un widget nu mai are lățime, iar sizeHint-ul lui iese altă cifră decât cât ocupa
    de fapt pe bară. De aici palpăirea din jurnal: scădeam 120 px când îl ascundeam și
    socoteam 30 px când verificam dacă încape. Acum ținem minte lățimea de dinainte.
    """

    def test_a_widget_is_measured_the_same_way_as_the_bar(self):
        """
        Cât cere o coloană se citește din sizeHint. Dacă pentru un widget luăm în schimb
        lățimea lui de pe ecran, cele două cifre nu mai sunt din aceeași măsură — iar din
        asta a ieșit vremea care apărea și dispărea la fiecare câteva minute.
        """
        w = FakeWidget(real=70, hint=102)
        self.assertEqual(ResponsiveWidget._width_of(w, hidden_by_us=False), 102)
        self.assertEqual(getattr(w, LAST_WIDTH), 102)

    def test_a_hidden_widget_keeps_the_width_it_had(self):
        w = FakeWidget(real=102, hint=102)
        ResponsiveWidget._width_of(w, hidden_by_us=False)
        w._hint = 30  # ascuns, unele widget-uri își strâng sizeHint-ul
        self.assertEqual(ResponsiveWidget._width_of(w, hidden_by_us=True), 102)

    def test_a_widget_we_never_saw_falls_back_to_its_size_hint(self):
        w = FakeWidget(real=0, hint=30)
        self.assertEqual(ResponsiveWidget._width_of(w, hidden_by_us=True), 30)

    def test_a_widget_without_a_width_yet_is_not_counted_as_zero(self):
        """0 px ar însemna „nu ocupă loc": l-am ascunde fără niciun câștig."""
        w = FakeWidget(real=0, hint=0)
        self.assertEqual(ResponsiveWidget._width_of(w, hidden_by_us=False), 1)


class TestTheArrowDoesNotSqueezeThingsOut(unittest.TestCase):
    """
    Săgeata de la capăt apare doar cât timp ceva e ascuns, dar ocupă și ea loc.

    Pe bara lui de 1280 px: locul era 1241 px (16 px margine + 23 px ținuți pentru săgeată),
    iar bara cerea 1250. Adică exact locul săgeții lipsea, vremea nu mai încăpea — și așa
    săgeata ajungea să provoace ascunderea care o scotea la iveală. Locul ei se ține abia
    după ce se știe că tot rămâne ceva ascuns.
    """

    SIDES = {"right": (1250, [("weather", 102, False)])}

    def test_nothing_is_hidden_when_it_fits_without_the_arrow(self):
        to_hide, _ = plan_bar(1264, 0, self.SIDES, 24)
        self.assertEqual(to_hide, [])
        self.assertFalse(still_hidden(self.SIDES, to_hide, []), "nu e nevoie de săgeată")

    def test_the_arrow_keeps_its_room_once_something_is_hidden(self):
        sides = {"right": (1300, [("weather", 102, False), ("ram", 70, False)])}
        to_hide, to_show = plan_bar(1264, 0, sides, 24)
        self.assertTrue(to_hide)
        self.assertTrue(still_hidden(sides, to_hide, to_show))

    def test_a_widget_we_already_hid_keeps_the_arrow_there(self):
        sides = {"right": (1100, [("weather", 102, True)])}
        self.assertTrue(still_hidden(sides, [], []))

    def test_bringing_the_last_one_back_lets_the_arrow_go(self):
        sides = {"right": (1100, [("weather", 102, True)])}
        self.assertFalse(still_hidden(sides, [], ["weather"]))


class TestSettlingDown(unittest.TestCase):
    """
    La pornire, bara se măsoară, dar nu ascunde nimic în primele secunde.

    În jurnal se vedea ce iese altfel: la fiecare pornire, patru runde de ascuns-arătat în
    șase secunde. Placa video și VRAM-ul se arată singure când le vine prima citire, la o
    secundă-două după bară; noi le ascunsesem deja, ele reapăreau, socoteala se relua.
    """

    SETTLE = ResponsiveConfig().settle

    def test_right_after_start_we_only_measure(self):
        self.assertFalse(settled(0, self.SETTLE))
        self.assertFalse(settled(self.SETTLE - 1, self.SETTLE))

    def test_then_we_may_hide(self):
        self.assertTrue(settled(self.SETTLE, self.SETTLE))
        self.assertTrue(settled(60_000, self.SETTLE))

    def test_the_wait_is_long_enough_for_the_graphics_card(self):
        """Placa video apare la o secundă-două după bară: așteptarea trebuie să treacă de ea."""
        self.assertGreaterEqual(self.SETTLE, 3000)

    def test_it_can_be_turned_off(self):
        self.assertTrue(settled(0, 0))


class TestLearningTheRealWidth(unittest.TestCase):
    """
    Cât ocupă de fapt un widget: cât s-a schimbat nevoia coloanei când l-am ascuns.

    sizeHint-ul lui nu cuprinde și spațiile din jur — marginile containerului, distanța dintre
    vecini. Deci când îl ascunzi se eliberează mai mult decât spune el. Din jurnal: memoria
    ocupa 112 px, dar se socotea cu ~76, așa că era adusă înapoi într-un loc de 100 px în care
    nu încăpea — ascunsă, arătată, la o secundă.
    """

    def test_the_measured_difference_wins(self):
        self.assertEqual(learned_width(76, 112), 112)

    def test_a_nonsense_jump_is_ignored(self):
        """Între timp se mai schimbă titlul ferestrei sau traficul: nu luăm orice cifră."""
        self.assertEqual(learned_width(76, 900), 76)
        self.assertEqual(learned_width(76, 4), 76)

    def test_a_widget_without_a_hint_takes_what_it_measured(self):
        self.assertEqual(learned_width(0, 112), 112)

    def test_once_learned_it_is_not_brought_back_into_too_little_room(self):
        """Exact cazul din jurnal: 100 px liberi, memoria cere 112 — rămâne ascunsă."""
        hidden_ram = [("ram", learned_width(76, 112), True)]
        _, to_show = plan_bar(1241, 0, {"right": (1141, hidden_ram)}, 24)
        self.assertEqual(to_show, [])

    def test_with_the_old_number_it_would_flap(self):
        """Dovada că cifra conta: cu sizeHint-ul, o aducea înapoi și o ascundea la loc."""
        hidden_ram = [("ram", 76, True)]
        _, to_show = plan_bar(1241, 0, {"right": (1141, hidden_ram)}, 24)
        self.assertEqual(to_show, ["ram"])
