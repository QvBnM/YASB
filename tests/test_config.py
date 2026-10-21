"""
Verificările care prind greșelile tăcute din config.yaml și styles.css, plus contractul cu YASB.

Azi, un nume de widget scris greșit într-o regulă (moduri, praguri, responsive) nu face nimic
și nu scrie nimic în jurnal: regula pur și simplu nu se aplică niciodată. La fel, o culoare
folosită în styles.css dar nescrisă în paletă rămâne nerezolvată. Aici amândouă cad ca teste.

Logica verificărilor stă în tools/mint_check.py și e aceeași pe care o rulează doctorul
înainte de instalare, ca să nu existe două adevăruri despre ce înseamnă „e în regulă”.
"""

import importlib
import sys
import textwrap
import unittest
from pathlib import Path

import stubs

stubs.install()

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mint_check import (  # noqa: E402
    CONFIG_DIR,
    CONTRACT_ATTRIBUTES,
    contract_problems,
    css_used_names,
    duplicate_keys,
    hardcoded_colours,
    load_config,
    missing_references,
    placed_widgets,
    referenced_widget_names,
    scan_yasb_imports,
    unresolved_css_vars,
    widgets_placed_twice,
)

CFG = load_config()
WIDGETS: dict = CFG.get("widgets", {})
NAMES = set(WIDGETS)
STYLES = (CONFIG_DIR / "styles.css").read_text(encoding="utf-8")
PALETTE = (CONFIG_DIR / "palette.css").read_text(encoding="utf-8")


def options(name: str) -> dict:
    return (WIDGETS.get(name, {}) or {}).get("options", {}) or {}


class TestReferences(unittest.TestCase):
    """Orice widget numit într-o regulă trebuie să existe cu adevărat."""

    def test_every_referenced_widget_exists(self):
        missing = missing_references(CFG)
        self.assertEqual(missing, [], "widget-uri numite dar inexistente:\n  " + "\n  ".join(missing))

    def test_the_scan_actually_looks_everywhere(self):
        """Dacă cineva adaugă o regulă nouă și uită să o treacă în scanare, testul de sus devine gol."""
        places = referenced_widget_names(CFG)
        for expected in (
            "bars.primary-bar.left",
            "media_group.widgets",
            "modes.hidden_by_default",
            "responsive.hide_left",
            "thresholds.rules",
            "cover_accent.targets",
            "notif.replace",
            "launcher.bar_commands",
        ):
            self.assertIn(expected, places, f"scanarea nu se mai uită la {expected}")
        self.assertGreater(sum(len(v) for v in places.values()), 40)

    def test_a_typo_is_caught(self):
        broken = {
            "widgets": {"cpu": {"type": "yasb.cpu.CpuWidget"}},
            "bars": {"b": {"widgets": {"right": ["cpuu"]}}},
        }
        self.assertEqual(missing_references(broken), ["bars.b.right -> 'cpuu'"])

    def test_every_widget_is_actually_placed_in_a_bar(self):
        unused = sorted(NAMES - placed_widgets(CFG))
        # speedtest e documentat ca nefolosit (testul e în popup-ul de rețea)
        self.assertEqual(unused, ["speedtest"], f"widget-uri definite dar nepuse nicăieri: {unused}")

    def test_no_widget_is_placed_twice(self):
        twice = widgets_placed_twice(CFG)
        self.assertEqual(twice, [], f"widget-uri puse de două ori: {twice}")


class TestSchemas(unittest.TestCase):
    """Opțiunile widget-urilor noastre trec prin schemele lor pydantic."""

    # Widget-uri care moștenesc schema unui widget YASB: sub stub-uri schema aceea e falsă,
    # deci nu se poate valida aici. Le verifică doctorul, pe calculatorul cu YASB instalat.
    INHERITED_SCHEMA = {"bluetooth"}

    @staticmethod
    def _is_real_schema(schema) -> bool:
        from pydantic import BaseModel

        return isinstance(schema, type) and issubclass(schema, BaseModel)

    def _mint_widgets(self):
        for name, widget in WIDGETS.items():
            kind = widget.get("type", "")
            if not kind.startswith("yasb."):
                continue
            module_name = "core.widgets.yasb." + kind.split(".")[1]
            if not (REPO / "src" / module_name.replace(".", "/")).with_suffix(".py").exists():
                continue  # widget YASB, nu al nostru
            yield name, kind, module_name

    def test_every_mint_widget_validates(self):
        failures = []
        skipped = []
        checked = 0
        for name, kind, module_name in self._mint_widgets():
            module = importlib.import_module(module_name)
            widget_class = getattr(module, kind.split(".")[2])
            schema = getattr(widget_class, "validation_schema", None)
            if not self._is_real_schema(schema):
                skipped.append(name)
                continue
            try:
                schema(**options(name))
                checked += 1
            except Exception as exc:
                failures.append(f"{name} ({kind}): {exc}")
        self.assertEqual(failures, [], "opțiuni respinse de scheme:\n  " + "\n  ".join(failures))
        self.assertGreater(checked, 10, "nu s-a validat aproape nimic: verifică potrivirea numelor")
        self.assertEqual(
            sorted(skipped),
            sorted(self.INHERITED_SCHEMA),
            "lista widget-urilor nevalidate aici s-a schimbat: actualizeaz-o conștient, nu din greșeală",
        )

    def test_defaults_alone_are_valid(self):
        """
        O schemă fără câmpuri obligatorii trebuie să meargă și fără nicio opțiune scrisă.
        Câmpurile obligatorii sunt în regulă (ex. folderul cu imagini al galeriei), dar atunci
        config.yaml chiar trebuie să le dea o valoare — altfel bara nu pornește.
        """
        failures = []
        for name, kind, module_name in self._mint_widgets():
            module = importlib.import_module(module_name)
            schema = getattr(getattr(module, kind.split(".")[2]), "validation_schema", None)
            if not self._is_real_schema(schema):
                continue
            required = sorted(f for f, info in schema.model_fields.items() if info.is_required())
            if required:
                absent = [f for f in required if f not in set(options(name))]
                if absent:
                    failures.append(f"{name} ({kind}): opțiuni obligatorii lipsă din config.yaml: {absent}")
                continue
            try:
                schema()
            except Exception as exc:
                failures.append(f"{kind}: {exc}")
        self.assertEqual(failures, [], "probleme cu valorile implicite:\n  " + "\n  ".join(failures))


class TestStyles(unittest.TestCase):
    """Fiecare culoare folosită în styles.css trebuie să existe în paletă."""

    def test_no_unresolved_colour(self):
        missing = unresolved_css_vars(STYLES, PALETTE)
        self.assertEqual(missing, [], f"culori folosite dar nedefinite în paletă: {missing}")

    def test_no_hardcoded_colour_in_the_bar(self):
        """Culorile vin din wallpaper: un hex scris direct nu s-ar mai schimba cu paleta."""
        hexes = hardcoded_colours(STYLES)
        self.assertEqual(hexes, [], f"culori scrise direct în styles.css: {hexes}")

    def test_a_missing_colour_is_caught(self):
        self.assertEqual(
            unresolved_css_vars(".x { color: var(--inexistent); }", ":root { --bar: #000000; }"),
            ["inexistent"],
        )

    def test_the_rgb_variants_count_as_defined(self):
        self.assertEqual(
            unresolved_css_vars(".x { background: rgba(var(--bar-rgb), .9); }", ":root { --bar: #000000; }"),
            [],
        )

    def test_palette_defines_everything_the_fallback_knows(self):
        from core.widgets.yasb.mint_common import FALLBACK_PALETTE
        from mint_check import css_defined_names

        missing = sorted(set(FALLBACK_PALETTE) - css_defined_names(STYLES, PALETTE))
        self.assertEqual(missing, [], f"paleta de exemplu nu are: {missing}")

    def test_the_bar_really_uses_colours(self):
        self.assertGreater(len(css_used_names(STYLES)), 10)


class TestContract(unittest.TestCase):
    """
    Lista lucrurilor din YASB pe care ne sprijinim, verificată pe un YASB de carton.

    Testul nu are YASB adevărat la îndemână, deci construiește un arbore mic de fișiere și
    verifică faptul că citirea chiar găsește ce lipsește — adică exact ce va face doctorul pe
    calculatorul tău, pe codul adevărat.
    """

    def _fake_yasb(self, body: str, module: str = "core/widgets/yasb/windows_desktops.py") -> Path:
        import tempfile

        root = Path(tempfile.mkdtemp())
        path = root / module
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return root

    def test_the_import_list_is_read_from_our_own_code(self):
        """Lista nu se scrie de mână, deci nu poate rămâne în urmă."""
        imports = scan_yasb_imports()
        self.assertIn("core.widgets.base", imports)
        self.assertIn("BaseWidget", imports["core.widgets.base"])
        self.assertIn("core.widgets.yasb.pomodoro", imports)
        # modulele noastre nu sunt „împrumutate din YASB”
        self.assertNotIn("core.widgets.yasb.mint_common", imports)
        self.assertNotIn("core.validation.widgets.yasb.responsive", imports)

    def test_our_own_modules_taken_from_a_yasb_package_are_not_counted(self):
        """
        „from core.widgets.yasb import mint_visibility” ia un modul al nostru dintr-un pachet
        al lor. Pachetul e al YASB, modulul e al nostru — deci nu e nimic de verificat acolo.
        Fără distincția asta, doctorul cerea YASB-ului niște nume pe care le-am scris noi.
        """
        from_package = scan_yasb_imports().get("core.widgets.yasb", set())
        for ours in ("mint_visibility", "mint_text", "mint_common", "bar_overflow"):
            self.assertNotIn(ours, from_package, f"'{ours}' e al nostru, nu al YASB")
        self.assertIn("clock", from_package, "clock chiar vine din YASB și trebuie verificat")

    def test_a_missing_class_is_reported(self):
        root = self._fake_yasb("""
            class WorkspaceButton:
                workspace_index = 0
        """)
        problems, _notes = contract_problems(root)
        self.assertTrue(
            any("WorkspaceWidget" in p for p in problems),
            f"clasa lipsă nu a fost raportată: {problems}",
        )

    def test_a_missing_attribute_is_reported(self):
        root = self._fake_yasb("""
            class WorkspaceWidget:
                def __init__(self):
                    self.workspace_buttons = []
                def _update_button(self):
                    pass

            class WorkspaceButton:
                workspace_index = 0
        """)
        problems, _notes = contract_problems(root)
        self.assertTrue(
            any("_svc" in p for p in problems),
            f"atributul lipsă nu a fost raportat: {problems}",
        )

    def test_an_inherited_attribute_counts(self):
        root = self._fake_yasb("""
            class Base:
                def __init__(self):
                    self._svc = None

            class WorkspaceWidget(Base):
                def __init__(self):
                    super().__init__()
                    self.workspace_buttons = []
                def _update_button(self):
                    pass

            class WorkspaceButton:
                workspace_index = 0
        """)
        problems, _notes = contract_problems(root)
        self.assertFalse(any("_svc" in p for p in problems), f"atributul moștenit a fost ratat: {problems}")

    def test_a_file_that_cannot_be_read_is_a_note_not_a_problem(self):
        """YASB e scris pentru Python 3.14: citit cu o versiune mai veche, unele fișiere nu se analizează."""
        root = self._fake_yasb("asta nu e Python valid (((")
        problems, notes = contract_problems(root)
        self.assertTrue(any("windows_desktops" in n for n in notes), f"nu s-a notat fișierul necitit: {notes}")
        self.assertFalse(
            any("windows_desktops nu mai are" in p for p in problems),
            f"un fișier necitit nu trebuie raportat ca lipsă: {problems}",
        )

    def test_the_attribute_list_is_not_empty(self):
        """Dacă lista se golește din greșeală, verificarea devine o formalitate."""
        total = sum(len(attrs) for classes in CONTRACT_ATTRIBUTES.values() for attrs in classes.values())
        self.assertGreater(total, 20, "contractul cu YASB a rămas aproape gol")


if __name__ == "__main__":
    unittest.main()


class TestDuplicateKeys(unittest.TestCase):
    """
    Aceeași cheie scrisă de două ori în același loc.

    YAML nu se plânge: păstrează tăcut ultima și o aruncă pe prima. Scrii o setare, o vezi
    în fișier, și ea nu face nimic. Mi s-a întâmplat exact asta: am pus un `options:` nou
    sub `ui_ro`, care avea deja unul, iar setarea nouă a fost înghițită — și nicio
    verificare n-a zis nimic.
    """

    def test_the_real_config_has_none(self):
        text = (REPO / "config" / "config.yaml").read_text(encoding="utf-8")
        self.assertEqual(duplicate_keys(text), [])

    def test_it_catches_a_repeated_key(self):
        text = "widgets:\n  a:\n    options:\n      x: 1\n    options:\n      y: 2\n"
        found = duplicate_keys(text)
        self.assertEqual(len(found), 1)
        self.assertIn("widgets.a.options", found[0])

    def test_the_same_key_in_different_places_is_fine(self):
        text = "widgets:\n  a:\n    options:\n      x: 1\n  b:\n    options:\n      x: 2\n"
        self.assertEqual(duplicate_keys(text), [])

    def test_it_looks_inside_lists_too(self):
        text = "modes:\n  - name: call\n    hide: []\n    hide: [x]\n"
        self.assertTrue(duplicate_keys(text))
