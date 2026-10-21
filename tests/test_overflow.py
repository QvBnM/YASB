"""
Butonul de la capătul barei: ce nu mai încape, la un click distanță.

Regula care contează: lista arată exact ce a ascuns bara din lipsă de loc — nici mai mult,
nici mai puțin. Un widget ascuns de un mod automat (media, în modul joc) sau de el însuși
(temperatura, fără HWiNFO) nu e „pe dinafară”: e ascuns cu rost, și n-are ce căuta în listă.
"""

import sys
import unittest
from pathlib import Path

import stubs

stubs.install()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from core.validation.widgets.yasb.bar_overflow import BarOverflowConfig, OverflowEntry  # noqa: E402
from core.widgets.yasb.bar_overflow import rows_for, widget_text  # noqa: E402


class FakeLabel:
    def __init__(self, text: str, hidden: bool = False):
        self._text = text
        self._hidden = hidden

    def text(self) -> str:
        return self._text

    def isHidden(self) -> bool:  # noqa: N802 - nume Qt
        return self._hidden


class FakeWidget:
    def __init__(self, name: str, *labels):
        self.widget_name = name
        self._widgets = list(labels)


class Dead(FakeWidget):
    @property
    def _widgets(self):  # type: ignore[override]
        raise RuntimeError("wrapped C/C++ object has been deleted")

    @_widgets.setter
    def _widgets(self, _value):
        pass


class TestRows(unittest.TestCase):
    KNOWN = {"gpu": object(), "ram": object(), "weather": object()}

    def test_only_what_is_hidden_is_listed(self):
        entries = [OverflowEntry(widget="gpu", title="Placa video"), OverflowEntry(widget="ram", title="Memorie")]
        rows = rows_for(["gpu"], entries, self.KNOWN)
        self.assertEqual(rows, [("Placa video", "", "gpu")])

    def test_nothing_hidden_means_an_empty_list(self):
        entries = [OverflowEntry(widget="gpu", title="Placa video")]
        self.assertEqual(rows_for([], entries, self.KNOWN), [])

    def test_the_configured_order_is_kept(self):
        entries = [
            OverflowEntry(widget="weather", title="Vremea"),
            OverflowEntry(widget="gpu", title="Placa video"),
            OverflowEntry(widget="ram", title="Memorie"),
        ]
        rows = rows_for(["ram", "gpu", "weather"], entries, self.KNOWN)
        self.assertEqual([r[0] for r in rows], ["Vremea", "Placa video", "Memorie"])

    def test_without_a_list_everything_hidden_shows_up(self):
        rows = rows_for(["gpu", "ram"], [], self.KNOWN)
        self.assertEqual([r[2] for r in rows], ["gpu", "ram"])

    def test_a_widget_that_is_not_in_the_bar_is_skipped(self):
        rows = rows_for(["gpu", "inexistent"], [], self.KNOWN)
        self.assertEqual([r[2] for r in rows], ["gpu"])

    def test_a_title_falls_back_to_the_widget_name(self):
        rows = rows_for(["gpu"], [OverflowEntry(widget="gpu")], self.KNOWN)
        self.assertEqual(rows[0][0], "gpu")

    def test_entries_for_widgets_the_bar_never_hid_are_ignored(self):
        """Lista nu inventează rânduri: dacă bara n-a ascuns nimic, lista e goală."""
        entries = [OverflowEntry(widget=f"w{i}", title=f"W{i}") for i in range(10)]
        self.assertEqual(rows_for([], entries, {}), [])


class TestWidgetText(unittest.TestCase):
    """Valoarea din listă se citește din etichetele pe care widget-ul le ține oricum la zi."""

    def test_labels_are_joined(self):
        widget = FakeWidget("gpu", FakeLabel("GPU"), FakeLabel("42"), FakeLabel("%"))
        self.assertEqual(widget_text(widget), "GPU 42 %")

    def test_hidden_labels_are_left_out(self):
        """La lățimi mici unitățile sunt ascunse: nu le punem înapoi în listă."""
        widget = FakeWidget("gpu", FakeLabel("GPU"), FakeLabel("42"), FakeLabel("%", hidden=True))
        self.assertEqual(widget_text(widget), "GPU 42")

    def test_empty_labels_do_not_leave_gaps(self):
        widget = FakeWidget("gpu", FakeLabel("GPU"), FakeLabel("   "), FakeLabel("42"))
        self.assertEqual(widget_text(widget), "GPU 42")

    def test_a_widget_without_labels(self):
        self.assertEqual(widget_text(FakeWidget("gol")), "")

    def test_a_destroyed_widget_does_not_raise(self):
        self.assertEqual(widget_text(Dead("mort")), "")


class TestConfig(unittest.TestCase):
    def test_the_defaults_work_on_their_own(self):
        config = BarOverflowConfig()
        self.assertEqual(config.entries, [])
        self.assertGreaterEqual(config.refresh_interval, 250)

    def test_the_bar_config_lists_real_widgets(self):
        """Fiecare rând din listă trebuie să numească un widget care chiar există."""
        from mint_check import load_config

        cfg = load_config()
        widgets = set(cfg.get("widgets", {}))
        options = (cfg["widgets"]["overflow"].get("options") or {})
        named = [e["widget"] for e in options.get("entries") or []]
        self.assertTrue(named, "lista e goală în config.yaml")
        missing = [n for n in named if n not in widgets]
        self.assertEqual(missing, [], f"rânduri care numesc widget-uri inexistente: {missing}")

    def test_the_arrow_sits_in_the_bar(self):
        from mint_check import load_config, placed_widgets

        self.assertIn("overflow", placed_widgets(load_config()))


if __name__ == "__main__":
    unittest.main()
