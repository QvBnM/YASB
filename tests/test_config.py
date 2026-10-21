"""
Verificările care prind greșelile tăcute din config.yaml și styles.css.

Azi, un nume de widget scris greșit într-o regulă (moduri, praguri, responsive) nu face nimic
și nu scrie nimic în jurnal: regula pur și simplu nu se aplică niciodată. La fel, o culoare
folosită în styles.css dar nescrisă în paletă rămâne nerezolvată. Aici amândouă cad ca teste.
"""

import importlib
import re
import unittest
from pathlib import Path

import yaml

import stubs

stubs.install()

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "config.yaml"
STYLES = REPO / "config" / "styles.css"
PALETTE = REPO / "config" / "palette.css"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


CFG = load_config()
WIDGETS: dict = CFG.get("widgets", {})
NAMES = set(WIDGETS)


def options(name: str) -> dict:
    return WIDGETS.get(name, {}).get("options", {}) or {}


def referenced_names() -> dict[str, list[str]]:
    """Fiecare loc din config care numește alte widget-uri -> numele numite."""
    out: dict[str, list[str]] = {}

    for bar_name, bar in (CFG.get("bars") or {}).items():
        for column, items in (bar.get("widgets") or {}).items():
            out[f"bars.{bar_name}.{column}"] = list(items or [])

    for name, widget in WIDGETS.items():
        kind = widget.get("type", "")
        opts = options(name)
        if kind.endswith("grouper.GrouperWidget"):
            out[f"{name}.widgets"] = list(opts.get("widgets") or [])
        if kind.endswith("context_mode.ContextModeWidget"):
            out[f"{name}.hidden_by_default"] = list(opts.get("hidden_by_default") or [])
            for mode in opts.get("modes") or []:
                label = mode.get("name", "?")
                out[f"{name}.{label}.hide"] = list(mode.get("hide") or [])
                out[f"{name}.{label}.show"] = list(mode.get("show") or [])
        if kind.endswith("responsive.ResponsiveWidget"):
            out[f"{name}.hide_left"] = list(opts.get("hide_left") or [])
            out[f"{name}.hide_right"] = list(opts.get("hide_right") or [])
            out[f"{name}.flexible"] = list((opts.get("flexible") or {}).keys())
        if kind.endswith("mint_thresholds.MintThresholdsWidget"):
            out[f"{name}.rules"] = [r["widget"] for r in opts.get("rules") or [] if "widget" in r]
        if kind.endswith("cover_accent.CoverAccentWidget"):
            out[f"{name}.targets"] = list(opts.get("targets") or [])
        if kind.endswith("bar_notifications.BarNotificationsWidget"):
            replace = opts.get("replace")
            if replace:
                out[f"{name}.replace"] = [replace]
        if kind.endswith("quick_launch.QuickLaunchWidget"):
            commands = ((opts.get("providers") or {}).get("bar_commands") or {}).get("commands") or []
            out[f"{name}.bar_commands"] = [c["widget"] for c in commands if c.get("widget")]
    return out


class TestReferences(unittest.TestCase):
    """Orice widget numit într-o regulă trebuie să existe cu adevărat."""

    def test_every_referenced_widget_exists(self):
        missing = []
        for where, names in referenced_names().items():
            for name in names:
                if name not in NAMES:
                    missing.append(f"{where} -> '{name}'")
        self.assertEqual(missing, [], "widget-uri numite dar inexistente:\n  " + "\n  ".join(missing))

    def test_every_widget_is_actually_placed_in_a_bar(self):
        """Un widget definit dar nepus în nicio bară nu rulează niciodată."""
        placed: set[str] = set()
        for bar in (CFG.get("bars") or {}).values():
            for items in (bar.get("widgets") or {}).values():
                placed.update(items or [])
        for name, widget in WIDGETS.items():
            if widget.get("type", "").endswith("grouper.GrouperWidget"):
                placed.update(options(name).get("widgets") or [])
        unused = sorted(NAMES - placed)
        # speedtest e documentat ca nefolosit (testul e în popup-ul de rețea)
        self.assertEqual(unused, ["speedtest"], f"widget-uri definite dar nepuse nicăieri: {unused}")

    def test_no_widget_is_placed_twice(self):
        seen: dict[str, str] = {}
        twice = []
        for bar_name, bar in (CFG.get("bars") or {}).items():
            for column, items in (bar.get("widgets") or {}).items():
                for name in items or []:
                    where = f"bars.{bar_name}.{column}"
                    if name in seen:
                        twice.append(f"'{name}' ({seen[name]} și {where})")
                    seen[name] = where
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
                written = set(options(name))
                absent = [f for f in required if f not in written]
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

    USED = re.compile(r"var\(\s*--([\w-]+)\s*\)")
    DEFINED = re.compile(r"--([\w-]+)\s*:")

    def defined_names(self) -> set[str]:
        names = set(self.DEFINED.findall(PALETTE.read_text(encoding="utf-8")))
        # styles.css își definește singur rezerva pentru --warn, înaintea importului
        head = STYLES.read_text(encoding="utf-8").split("@import", 1)[0]
        names |= set(self.DEFINED.findall(head))
        # generatorul scrie și varianta "r, g, b" pentru fiecare culoare
        names |= {f"{n}-rgb" for n in names}
        return names

    def used_names(self) -> set[str]:
        return set(self.USED.findall(STYLES.read_text(encoding="utf-8")))

    def test_no_unresolved_colour(self):
        missing = sorted(self.used_names() - self.defined_names())
        self.assertEqual(missing, [], f"culori folosite dar nedefinite în paletă: {missing}")

    def test_no_hardcoded_colour_in_the_bar(self):
        """Culorile vin din wallpaper: un hex scris direct nu s-ar mai schimba cu paleta."""
        body = STYLES.read_text(encoding="utf-8").split("@import", 1)[1]
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
        self.assertEqual(hexes, [], f"culori scrise direct în styles.css: {hexes}")

    def test_palette_defines_everything_the_fallback_knows(self):
        from core.widgets.yasb.mint_common import FALLBACK_PALETTE

        defined = self.defined_names()
        missing = sorted(set(FALLBACK_PALETTE) - defined)
        self.assertEqual(missing, [], f"paleta de exemplu nu are: {missing}")


if __name__ == "__main__":
    unittest.main()
