"""
Arbitrul de vizibilitate: un singur șef, trei păreri.

Testul cel mai important e `test_a_widget_hidden_by_a_mode_stays_hidden`: exact situația care
făcea bara să sară — temperatura procesorului reapărea singură la fiecare două secunde, peste
modul de joc care tocmai o ascunsese.
"""

import unittest

import stubs

stubs.install()

from core.widgets.yasb.mint_visibility import (  # noqa: E402
    ESCAPE_LIMIT,
    MODE,
    SELF,
    SPACE,
    effective,
    escaped,
    hidden_by,
    is_visible,
    request,
    self_managed,
    wants,
)


class FakeWidget:
    """Un widget de carton care ține minte ce i s-a cerut, ca un QWidget adevărat."""

    def __init__(self, visible: bool = True):
        self._hidden = not visible
        self.calls: list[bool] = []

    def isHidden(self) -> bool:  # noqa: N802 - nume Qt
        return self._hidden

    def setVisible(self, visible: bool) -> None:  # noqa: N802 - nume Qt
        self.calls.append(visible)
        self._hidden = not visible


class Destroyed(FakeWidget):
    """Un widget care a fost distrus între timp: Qt aruncă RuntimeError la orice atingere."""

    def isHidden(self) -> bool:  # noqa: N802
        raise RuntimeError("wrapped C/C++ object has been deleted")


class TestTruthTable(unittest.TestCase):
    def test_nobody_objects_means_visible(self):
        self.assertTrue(effective({}))

    def test_a_missing_opinion_counts_as_yes(self):
        self.assertTrue(effective({MODE: True}))

    def test_any_single_no_hides_it(self):
        for owner in (MODE, SPACE, SELF):
            self.assertFalse(effective({owner: False}), f"{owner} singur ar trebui să ascundă")

    def test_all_yes_shows_it(self):
        self.assertTrue(effective({MODE: True, SPACE: True, SELF: True}))

    def test_who_is_hiding_it(self):
        self.assertEqual(hidden_by({MODE: False, SPACE: True, SELF: False}), [MODE, SELF])
        self.assertEqual(hidden_by({}), [])


class TestRequests(unittest.TestCase):
    def test_one_no_hides_the_widget(self):
        w = FakeWidget()
        self.assertTrue(request(w, MODE, False))
        self.assertTrue(w.isHidden())

    def test_repeating_the_same_opinion_changes_nothing(self):
        w = FakeWidget()
        request(w, MODE, False)
        before = len(w.calls)
        for _ in range(5):
            self.assertFalse(request(w, MODE, False))
        self.assertEqual(len(w.calls), before, "nu are voie să atingă widget-ul degeaba")

    def test_a_widget_hidden_by_a_mode_stays_hidden(self):
        """Cazul care făcea bara să sară: temperatura se re-arăta singură peste modul de joc."""
        w = FakeWidget()
        request(w, MODE, False)  # modul de joc: nu-ți stă locul aici
        for _ in range(10):  # cronometrul widget-ului, la fiecare două secunde
            request(w, SELF, True)  # am date, aș vrea să mă arăt
        self.assertTrue(w.isHidden(), "widget-ul a reapărut peste mod")
        self.assertEqual(w.calls, [False], "bara a fost atinsă de mai multe ori")

    def test_it_comes_back_when_the_mode_lets_it(self):
        w = FakeWidget()
        request(w, MODE, False)
        request(w, SELF, True)
        self.assertTrue(w.isHidden())
        request(w, MODE, True)
        self.assertFalse(w.isHidden())

    def test_no_room_and_no_data_both_have_to_clear(self):
        w = FakeWidget()
        request(w, SPACE, False)
        request(w, SELF, False)
        request(w, SPACE, True)
        self.assertTrue(w.isHidden(), "încă n-are ce arăta")
        request(w, SELF, True)
        self.assertFalse(w.isHidden())

    def test_opinions_are_read_back_separately(self):
        w = FakeWidget()
        request(w, SPACE, False)
        self.assertFalse(wants(w, SPACE))
        self.assertTrue(wants(w, MODE))
        self.assertTrue(wants(w, SELF))
        self.assertFalse(is_visible(w))

    def test_the_state_lives_on_the_widget(self):
        """Fără registru global: când widget-ul dispare, dispare și părerea despre el."""
        a, b = FakeWidget(), FakeWidget()
        request(a, MODE, False)
        self.assertTrue(a.isHidden())
        self.assertFalse(b.isHidden())
        self.assertTrue(wants(b, MODE))

    def test_a_destroyed_widget_does_not_raise(self):
        w = Destroyed()
        self.assertFalse(request(w, MODE, False))

    def test_we_never_show_what_we_did_not_hide(self):
        """Widget-urile YASB se ascund singure (media fără melodie). Nu ne băgăm peste ele."""
        w = FakeWidget(visible=False)  # ascuns de YASB, nu de noi
        self.assertFalse(request(w, MODE, True))
        self.assertTrue(w.isHidden(), "l-am arătat deși nu noi îl ascunsesem")
        self.assertEqual(w.calls, [])

    def test_we_do_show_again_what_we_hid(self):
        w = FakeWidget()
        request(w, SPACE, False)
        self.assertTrue(w.isHidden())
        request(w, SPACE, True)
        self.assertFalse(w.isHidden())

    def test_hiding_is_always_allowed_even_over_someone_else(self):
        w = FakeWidget(visible=True)
        request(w, MODE, False)
        self.assertTrue(w.isHidden())


class TestResponsiveCooperation(unittest.TestCase):
    """
    Widget-ul responsive se ocupă doar de loc, și doar de widget-urile care au voie să se vadă.

    Fără asta, el ar încerca să „aducă înapoi” un widget pe care un mod l-a ascuns, iar cele două
    s-ar bate pe fiecare tick.
    """

    def test_responsive_skips_what_is_not_its_business(self):
        hidden_by_mode = FakeWidget()
        request(hidden_by_mode, MODE, False)
        no_data = FakeWidget()
        request(no_data, SELF, False)
        normal = FakeWidget()

        candidates = [w for w in (hidden_by_mode, no_data, normal) if wants(w, MODE) and wants(w, SELF)]
        self.assertEqual(candidates, [normal])

    def test_responsive_can_tell_what_it_hid_itself(self):
        w = FakeWidget()
        request(w, SPACE, False)
        self.assertTrue(wants(w, MODE) and wants(w, SELF))
        self.assertFalse(wants(w, SPACE), "trebuie să știe că el l-a ascuns, ca să-l poată aduce înapoi")


if __name__ == "__main__":
    unittest.main()


class SelfShowing(FakeWidget):
    """
    Widget-ul care se arată singur.

    Placa video din YASB cheamă `show()` la fiecare citire proprie, dacă are ce afișa. Până
    acum noi credeam că l-am ascuns, el se vedea, iar socoteala de loc rămânea greșită la
    nesfârșit: scădeam un widget care de fapt ocupa loc, deci ascundeam altele degeaba.
    """

    def poll(self) -> None:
        self._hidden = False


class TestEscape(unittest.TestCase):
    def test_a_widget_that_shows_itself_again_is_noticed(self):
        w = SelfShowing()
        request(w, SPACE, False)
        self.assertTrue(w.isHidden())
        w.poll()
        self.assertTrue(escaped(w), "nu a observat că widget-ul se vede")

    def test_our_opinion_is_dropped_so_the_arithmetic_is_right_again(self):
        w = SelfShowing()
        request(w, SPACE, False)
        w.poll()
        escaped(w)
        self.assertTrue(wants(w, SPACE), "încă socotim că l-am ascuns, deși se vede")

    def test_someone_elses_opinion_survives(self):
        """Dacă un mod îl voia ascuns și el s-a arătat oricum, părerea modului nu e respectată."""
        w = SelfShowing()
        request(w, MODE, False)
        w.poll()
        escaped(w)
        self.assertTrue(wants(w, MODE))

    def test_it_is_reported_only_once_per_escape(self):
        w = SelfShowing()
        request(w, SPACE, False)
        w.poll()
        self.assertTrue(escaped(w))
        self.assertFalse(escaped(w), "ar scrie în jurnal la fiecare secundă")

    def test_after_a_few_tries_we_leave_it_alone(self):
        w = SelfShowing()
        for _ in range(ESCAPE_LIMIT):
            request(w, SPACE, False)
            w.poll()
            escaped(w)
        self.assertTrue(self_managed(w))
        w.calls.clear()
        self.assertFalse(request(w, SPACE, False), "încearcă din nou să ascundă ceva ce nu se lasă")
        self.assertEqual(w.calls, [])
        self.assertTrue(wants(w, SPACE), "a rămas o părere falsă în stare")

    def test_a_widget_that_stays_hidden_is_not_an_escape(self):
        w = FakeWidget()
        request(w, SPACE, False)
        self.assertFalse(escaped(w))
        self.assertFalse(self_managed(w))

    def test_a_widget_hidden_by_someone_else_is_not_our_escape(self):
        """YASB îl ascunde singur (media fără melodie), apoi îl arată: nu e treaba noastră."""
        w = FakeWidget(visible=False)
        request(w, SPACE, False)  # noi nu l-am ascuns: era deja ascuns
        w._hidden = False
        self.assertFalse(escaped(w))

    def test_a_destroyed_widget_does_not_crash(self):
        w = Destroyed()
        request(w, SPACE, False)
        self.assertFalse(escaped(w))
