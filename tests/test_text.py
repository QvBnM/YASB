"""
Traseul textului: traducere, apoi tăiere la lățime, apoi culoarea de prag.

Înainte, trei lucruri înlocuiau metoda setText peste ce găseau, deci ordinea era dată de cine
ajungea primul la etichetă — iar ordinea schimbă rezultatul. Aici ordinea e scrisă în clar și
verificată.
"""

import unittest

import stubs

stubs.install()

from core.widgets.yasb import mint_text  # noqa: E402
from core.widgets.yasb.mint_text import FIT, TRANSLATE  # noqa: E402


class FakeLabel:
    """O etichetă de carton: ține textul, ca un QLabel adevărat."""

    def __init__(self, text: str = ""):
        self._text = text
        self.writes: list[str] = []

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 - nume Qt
        self._text = text
        self.writes.append(text)


class TestPipeline(unittest.TestCase):
    def test_a_plain_label_passes_the_text_through(self):
        label = FakeLabel()
        label.setText("Salut")
        self.assertEqual(label.text(), "Salut")

    def test_one_stage_changes_the_text(self):
        label = FakeLabel()
        mint_text.add_stage(label, "translate", lambda t: t.replace("Networks", "Rețele"), TRANSLATE)
        label.setText("WiFi Networks")
        self.assertEqual(label.text(), "WiFi Networks".replace("Networks", "Rețele"))

    def test_the_order_is_written_down_not_accidental(self):
        """Traducerea vine prima: tăierea trebuie să lucreze pe textul care chiar se va vedea."""
        label = FakeLabel()
        seen: list[str] = []

        def translate(text):
            seen.append(f"translate:{text}")
            return text.replace("Week", "Săptămâna")

        def fit(text):
            seen.append(f"fit:{text}")
            return text[:10]

        # le înregistrăm în ordinea „greșită” înadins: ordinea o dau numerele, nu apelurile
        mint_text.add_stage(label, "fit", fit, FIT)
        mint_text.add_stage(label, "translate", translate, TRANSLATE)
        seen.clear()
        label.setText("Week 43")
        self.assertEqual(seen, ["translate:Week 43", "fit:Săptămâna 43"])
        self.assertEqual(label.text(), "Săptămâna ")  # 10 caractere, spațiul inclus

    def test_registering_the_same_stage_twice_does_not_double_it(self):
        label = FakeLabel()
        for _ in range(3):
            mint_text.add_stage(label, "translate", lambda t: t + "!", TRANSLATE)
        label.setText("a")
        self.assertEqual(label.text(), "a!")

    def test_a_stage_can_be_replaced(self):
        label = FakeLabel()
        mint_text.add_stage(label, "translate", lambda t: t + "1", TRANSLATE)
        mint_text.add_stage(label, "translate", lambda t: t + "2", TRANSLATE)
        label.setText("a")
        self.assertEqual(label.text(), "a2")

    def test_the_raw_text_is_kept(self):
        """Titlul întreg trebuie păstrat, altfel tăierea ar tăia din ce era deja tăiat."""
        label = FakeLabel()
        mint_text.add_stage(label, "fit", lambda t: t[:6], FIT)
        label.setText("Visual Studio Code")
        self.assertEqual(label.text(), "Visual")
        self.assertEqual(mint_text.raw_text(label), "Visual Studio Code")

    def test_re_running_starts_from_the_raw_text(self):
        label = FakeLabel()
        limit = {"width": 6}
        mint_text.add_stage(label, "fit", lambda t: t[: limit["width"]], FIT)
        label.setText("Visual Studio Code")
        self.assertEqual(label.text(), "Visual")
        limit["width"] = 13  # s-a eliberat loc lângă ceas
        mint_text.render(label)
        self.assertEqual(label.text(), "Visual Studio")

    def test_a_label_can_refuse_a_stage(self):
        """Titlul ferestrei e textul utilizatorului: nu are ce căuta prin traduceri."""
        label = FakeLabel()
        mint_text.add_stage(label, "translate", lambda t: "TRADUS", TRANSLATE)
        mint_text.exclude(label, "translate")
        label.setText("Rețetă pentru 6 clătite")
        self.assertEqual(label.text(), "Rețetă pentru 6 clătite")

    def test_a_broken_stage_does_not_lose_the_text(self):
        label = FakeLabel()

        def broken(_text):
            raise ValueError("ceva s-a stricat")

        mint_text.add_stage(label, "translate", broken, TRANSLATE)
        label.setText("Salut")
        self.assertEqual(label.text(), "Salut", "un pas stricat nu are voie să golească eticheta")

    def test_non_text_values_do_not_crash(self):
        label = FakeLabel()
        mint_text.add_stage(label, "translate", lambda t: t.upper(), TRANSLATE)
        label.setText(None)
        self.assertEqual(label.text(), "")
        label.setText(42)
        self.assertEqual(label.text(), "42")


class TestObservers(unittest.TestCase):
    """Pragul se uită la textul final, nu îl schimbă."""

    def test_the_observer_sees_what_the_user_sees(self):
        label = FakeLabel()
        seen: list[str] = []
        mint_text.add_stage(label, "translate", lambda t: t.replace("CPU", "PROC"), TRANSLATE)
        mint_text.add_observer(label, "thresholds", seen.append)
        seen.clear()
        label.setText("CPU 86")
        self.assertEqual(seen, ["PROC 86"])

    def test_an_observer_does_not_change_the_text(self):
        label = FakeLabel()
        mint_text.add_observer(label, "thresholds", lambda _t: "altceva")
        label.setText("86")
        self.assertEqual(label.text(), "86")

    def test_a_broken_observer_does_not_lose_the_text(self):
        label = FakeLabel()

        def broken(_text):
            raise ValueError("ceva s-a stricat")

        mint_text.add_observer(label, "thresholds", broken)
        label.setText("86")
        self.assertEqual(label.text(), "86")

    def test_the_threshold_reads_the_final_text(self):
        """
        Cazul care depindea de noroc: pragul calcula culoarea pe textul netradus dacă el
        apuca să prindă eticheta înaintea traducerii.
        """
        from core.widgets.yasb.mint_thresholds import evaluate
        from core.validation.widgets.yasb.mint_thresholds import ThresholdRule

        label = FakeLabel()
        levels: list[str | None] = []
        rules = [ThresholdRule(widget="cpu", warn=85, crit=95)]
        mint_text.add_stage(label, "fit", lambda t: t[:6], FIT)
        mint_text.add_observer(label, "thresholds", lambda text: levels.append(evaluate(text, rules)))
        levels.clear()
        label.setText("96 grade")
        self.assertEqual(label.text(), "96 gra")
        self.assertEqual(levels, ["crit"])


if __name__ == "__main__":
    unittest.main()
