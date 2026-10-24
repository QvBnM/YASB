"""
Bara se păzește singură: nicio piesă nu poate dărâma restul.

Fără asta, un widget care începe să crape la fiecare tick scrie un traceback pe secundă în
jurnal și mănâncă procesor la nesfârșit — iar tu afli despre el abia când deschizi jurnalul.
Aici verificăm că se oprește singur după trei greșeli apropiate și că restul merge înainte.
"""

import ast
import unittest
from pathlib import Path

import stubs

stubs.install()

from core.widgets.yasb import mint_health as health  # noqa: E402
from core.widgets.yasb.mint_health import ERROR_LIMIT, ERROR_WINDOW, should_stop  # noqa: E402


class FakeTimer:
    def __init__(self):
        self.running = True

    def stop(self) -> None:
        self.running = False


class TestShouldStop(unittest.TestCase):
    """Partea care decide, scrisă separat ca să poată fi probată fără cronometre adevărate."""

    def test_a_single_slip_is_not_a_pattern(self):
        self.assertFalse(should_stop([100.0], now=100.0))

    def test_two_are_still_not(self):
        self.assertFalse(should_stop([100.0, 101.0], now=101.0))

    def test_three_close_together_stop_it(self):
        self.assertTrue(should_stop([100.0, 101.0, 102.0], now=102.0))

    def test_three_spread_over_a_long_time_do_not(self):
        """O greșeală pe oră e altceva decât trei într-un minut."""
        old = [0.0, 3600.0, 7200.0]
        self.assertFalse(should_stop(old, now=7200.0))

    def test_exactly_on_the_window_edge_still_counts(self):
        times = [0.0, 1.0, 2.0]
        self.assertTrue(should_stop(times, now=ERROR_WINDOW))
        self.assertFalse(should_stop(times, now=ERROR_WINDOW + 2.1))

    def test_nothing_happened(self):
        self.assertFalse(should_stop([], now=10.0))


class TestGuard(unittest.TestCase):
    def setUp(self):
        health.reset()

    def test_a_working_widget_is_simply_counted(self):
        calls = []
        run = health.guard("ok", lambda: calls.append(1))
        for _ in range(5):
            run()
        state = health.status("ok")
        self.assertEqual(len(calls), 5)
        self.assertEqual(state.ticks, 5)
        self.assertEqual(state.errors, 0)
        self.assertFalse(state.stopped)

    def test_an_error_does_not_escape(self):
        def broken():
            raise ValueError("ceva s-a stricat")

        run = health.guard("rau", broken)
        run()  # nu are voie să arunce mai departe: ar opri cronometrul Qt
        self.assertEqual(health.status("rau").errors, 1)

    def test_three_errors_stop_the_widget_and_its_timer(self):
        timer = FakeTimer()

        def broken():
            raise ValueError("ceva s-a stricat")

        run = health.guard("rau", broken, stop=timer.stop)
        for _ in range(ERROR_LIMIT):
            run()
        state = health.status("rau")
        self.assertTrue(state.stopped)
        self.assertFalse(timer.running, "cronometrul a rămas pornit degeaba")
        self.assertIn("ValueError", state.stop_reason)

    def test_a_stopped_widget_is_not_called_again(self):
        calls = []

        def broken():
            calls.append(1)
            raise ValueError("ceva s-a stricat")

        run = health.guard("rau", broken, stop=FakeTimer().stop)
        for _ in range(10):
            run()
        self.assertEqual(len(calls), ERROR_LIMIT, "a continuat să fie chemat după ce s-a oprit")

    def test_one_broken_piece_does_not_touch_the_others(self):
        good = []
        run_good = health.guard("bun", lambda: good.append(1))

        def broken():
            raise ValueError("ceva s-a stricat")

        run_bad = health.guard("rau", broken, stop=FakeTimer().stop)
        for _ in range(5):
            run_bad()
            run_good()
        self.assertTrue(health.status("rau").stopped)
        self.assertFalse(health.status("bun").stopped)
        self.assertEqual(len(good), 5, "piesa bună a fost oprită odată cu cea stricată")

    def test_errors_a_widget_catches_itself_are_counted_too(self):
        """
        Widget-urile care își prind singure erorile trebuie să le și raporteze.

        Altfel paza nu le vede niciodată, iar o piesă stricată ar scrie la nesfârșit în jurnal
        fără să se oprească vreodată.
        """
        timer = FakeTimer()
        for _ in range(ERROR_LIMIT):
            health.failed("prins-singur", ValueError("x"), timer.stop)
        self.assertTrue(health.status("prins-singur").stopped)
        self.assertFalse(timer.running)

    def test_the_time_it_takes_is_measured(self):
        run = health.guard("masurat", lambda: None)
        run()
        run()
        self.assertEqual(health.status("masurat").ticks, 2)
        self.assertGreaterEqual(health.status("masurat").average_ms, 0.0)


class TestReport(unittest.TestCase):
    def setUp(self):
        health.reset()

    def test_the_broken_ones_come_first(self):
        health.guard("bun", lambda: None)()
        health.failed("cu-erori", ValueError("x"))
        for _ in range(ERROR_LIMIT):
            health.failed("oprit", ValueError("x"))
        names = [s.name for s in health.report()]
        self.assertEqual(names[0], "oprit", "piesa oprită trebuie să fie prima în listă")
        self.assertEqual(names[1], "cu-erori")

    def test_each_line_says_something_useful(self):
        health.guard("bun", lambda: None)()
        line = health.status("bun").to_line()
        self.assertIn("bun", line)
        self.assertIn("treceri", line)

    def test_a_stopped_piece_says_why(self):
        for _ in range(ERROR_LIMIT):
            health.failed("oprit", TimeoutError("x"))
        line = health.status("oprit").to_line()
        self.assertIn("OPRIT", line)
        self.assertIn("TimeoutError", line)


class TestLogHygiene(unittest.TestCase):
    """
    Mesajul unei excepții poate conține un titlu de fereastră, o cale sau un nume de rețea.
    În jurnal scriem tipul excepției și widget-ul, atât.
    """

    def setUp(self):
        health.reset()

    def test_the_exception_message_is_not_kept(self):
        health.failed("x", ValueError("C:/Users/mihai/Secret/parola.txt"))
        state = health.status("x")
        self.assertEqual(state.last_error, "ValueError")
        self.assertNotIn("parola", state.last_error)
        self.assertNotIn("parola", state.stop_reason)
        self.assertNotIn("parola", state.to_line())


if __name__ == "__main__":
    unittest.main()


class TestEveryRepeatingTimerIsInTheNet(unittest.TestCase):
    """
    Un cronometru care se repetă trece prin `health.connect`, nu direct prin `timeout.connect`.

    Nu e o chestiune de stil: în PyQt6 o excepție netratată într-un slot nu rămâne la slot, ia
    tot procesul — adică exact ce scrie `mint_health` că nu trebuie să se poată întâmpla. Testul
    citește sursele, ca să nu se mai uite la următorul widget.

    Cronometrele cu `setSingleShot(True)` (debounce, ascunderea unei bule) nu intră la socoteală.
    """

    WIDGETS = Path(__file__).resolve().parent.parent / "src" / "core" / "widgets" / "yasb"

    def connected_directly(self, tree: ast.AST) -> list[str]:
        """Numele cronometrelor legate cu `X.timeout.connect(...)`, fără cele single-shot."""
        single_shot, direct = set(), []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            target = node.func.value
            if node.func.attr == "setSingleShot" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and arg.value:
                    single_shot.add(ast.unparse(target))
            elif node.func.attr == "connect" and isinstance(target, ast.Attribute):
                if target.attr == "timeout":
                    direct.append(ast.unparse(target.value))
        return [name for name in direct if name not in single_shot]

    def test_no_widget_connects_a_repeating_timer_by_hand(self):
        missed = {}
        for path in sorted(self.WIDGETS.glob("*.py")):
            if path.name == "mint_health.py":
                continue  # chiar el e plasa: acolo e singurul timeout.connect care are voie
            names = self.connected_directly(ast.parse(path.read_text(encoding="utf-8")))
            if names:
                missed[path.name] = names
        self.assertEqual(missed, {}, f"cronometre repetitive în afara plasei: {missed}")
