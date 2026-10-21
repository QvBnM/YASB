"""
Regulile de design, verificate ca orice altceva.

Mărimile și rotunjirile erau valori nimerite una câte una: douăsprezece mărimi de text,
dintre care cinci la jumătate de pixel una de alta, și opt rotunjiri. Jumătate de pixel se
rotunjește la același pixel la 100 % și la pixeli diferiți la 125 %, deci aceeași bară arăta
altfel pe laptop și pe monitorul mare.

Testele de aici nu judecă gustul. Verifică doar că regulile rămân reguli: că nimeni nu mai
scrie o mărime direct în stiluri, că treptele rămân distincte la orice scalare Windows, și că
lucrurile pe care dai click dau un semn.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mint_check import CONFIG_DIR, css_defined_names, css_used_names  # noqa: E402

STYLES = (CONFIG_DIR / "styles.css").read_text(encoding="utf-8")
PALETTE = (CONFIG_DIR / "palette.css").read_text(encoding="utf-8")
COMMENT = re.compile(r"/\*.*?\*/", re.S)
BODY = COMMENT.sub("", STYLES).split("@import", 1)[1]
TOKENS = COMMENT.sub("", STYLES).split("@import", 1)[0]

# Scara Windows pe care o poate avea un ecran. Jumătățile de pixel se rotunjesc diferit
# de la una la alta — de acolo venea bara care nu arăta la fel pe două calculatoare.
SCALINGS = (1.0, 1.25, 1.5, 1.75, 2.0)


def token_value(name: str) -> float:
    match = re.search(rf"--{name}\s*:\s*([0-9.]+)px\s*;", TOKENS)
    assert match, f"jetonul --{name} nu există"
    return float(match.group(1))


class TestNoLooseValues(unittest.TestCase):
    """Mărimile și rotunjirile se scriu o singură dată, în blocul de jetoane."""

    def test_no_font_size_written_by_hand(self):
        loose = re.findall(r"font-size:\s*[0-9.]+px", BODY)
        self.assertEqual(loose, [], f"mărimi scrise direct, în afara scării: {loose}")

    def test_no_radius_written_by_hand(self):
        # 2px și 3px sunt grosimea unei bare de slider, nu rotunjirea unui obiect
        loose = [r for r in re.findall(r"border-radius:\s*([0-9.]+)px", BODY) if float(r) > 3]
        self.assertEqual(loose, [], f"rotunjiri scrise direct: {loose}")

    def test_the_text_scale_has_six_steps(self):
        steps = re.findall(r"--fs-([\w-]+)\s*:", TOKENS)
        self.assertEqual(len(steps), 6, f"scara de text are {len(steps)} trepte, nu șase: {steps}")

    def test_there_are_four_radii(self):
        radii = re.findall(r"--r-([\w-]+)\s*:", TOKENS)
        self.assertEqual(sorted(radii), ["card", "chip", "pill", "popup"])


class TestTheScaleSurvivesScaling(unittest.TestCase):
    """
    Două trepte trebuie să rămână două trepte la orice scalare Windows.

    Asta era problema concretă: 11,5 px și 12 px se rotunjesc amândouă la 14 px la 125 %,
    deci ierarhia dispărea pe un laptop și reapărea pe monitorul mare.
    """

    def steps(self) -> list[float]:
        return sorted(float(v) for v in re.findall(r"--fs-[\w-]+\s*:\s*([0-9.]+)px", TOKENS))

    def test_no_two_steps_collapse_into_one(self):
        for scale in SCALINGS:
            drawn = [round(step * scale) for step in self.steps()]
            self.assertEqual(
                len(set(drawn)),
                len(drawn),
                f"la {scale:.2f}× două trepte ajung la același pixel: {drawn}",
            )

    def test_the_steps_are_whole_pixels(self):
        for step in self.steps():
            self.assertEqual(step, int(step), f"{step}px: jumătățile de pixel se rotunjesc imprevizibil")

    def test_icon_sizes_are_whole_pixels_too(self):
        for value in re.findall(r"--ic[\w-]*\s*:\s*([0-9.]+)px", TOKENS):
            self.assertEqual(float(value), int(float(value)), f"{value}px")


class TestPills(unittest.TestCase):
    """Cele trei pastile din bară: aceeași înălțime, aceeași poziție, aceeași rotunjire."""

    PILLS = (".status-group .container", ".pomodoro-widget.focus .widget-container", ".mint-toast")

    def rule(self, selector: str) -> str:
        match = re.search(re.escape(selector) + r"\s*\{(.*?)\}", BODY, re.S)
        self.assertIsNotNone(match, f"nu găsesc regula pentru {selector}")
        return match.group(1)

    def test_all_three_have_the_same_height(self):
        for selector in self.PILLS:
            self.assertIn("min-height: var(--pill-h)", self.rule(selector), selector)

    def test_all_three_sit_at_the_same_place(self):
        for selector in self.PILLS:
            self.assertIn("margin: var(--pill-m)", self.rule(selector), selector)

    def test_all_three_are_rounded_the_same(self):
        for selector in self.PILLS:
            self.assertIn("border-radius: var(--r-pill)", self.rule(selector), selector)

    def test_the_pill_fits_the_bar(self):
        """Pastila plus marginile ei trebuie să încapă exact în înălțimea barei."""
        height = token_value("pill-h")
        margin = token_value("pill-m")
        self.assertEqual(height + 2 * margin, 34, "pastila nu mai încape în bara de 34 px")


class TestFeedback(unittest.TestCase):
    """Jumătate din lucrurile pe care dai click nu dădeau niciun semn."""

    def test_clicking_things_light_up_on_hover(self):
        self.assertIn(".widget .widget-container:hover", BODY)

    def test_the_visualizer_is_not_a_button(self):
        self.assertIn(".audio-visualizer-widget .widget-container:hover", BODY)

    def test_the_state_colours_the_cell_not_just_the_glyph(self):
        """Microfonul mut trebuie să se vadă dintr-o privire, nu doar dacă te uiți la el."""
        for selector in (
            ".status-group .microphone-widget .icon.muted",
            ".status-group .battery-widget .icon.status-critical",
        ):
            rule = re.search(re.escape(selector) + r"\s*\{(.*?)\}", BODY, re.S)
            self.assertIsNotNone(rule, f"lipsește regula pentru {selector}")
            self.assertIn("background-color", rule.group(1), selector)

    def test_the_state_box_is_always_reserved(self):
        """Altfel bara s-ar lăți la fiecare mut, iar cifrele ar sări."""
        rule = re.search(r"\.status-group \.widget \.icon\s*\{(.*?)\}", BODY, re.S)
        self.assertIsNotNone(rule)
        self.assertIn("min-width", rule.group(1))

    def test_an_icon_that_changes_with_its_value_has_a_fixed_box(self):
        """
        O iconiță care schimbă glifa (mut / mic / mediu / tare) schimbă și lățimea.

        La volum se vedea limpede: iconița stă în capul barei, deci tot ce e la dreapta ei —
        titlul ferestrei, ora, partea dreaptă — se muta cu câțiva pixeli la fiecare mișcare a
        cursorului. Părea că „se mișcă bara cu totul". Cutia rezervată oprește asta din rădăcină.
        """
        for selector in (".audio-slider-widget .icon", ".status-group .widget .icon"):
            widths = re.findall(re.escape(selector) + r"\s*\{(.*?)\}", BODY, re.S)
            self.assertTrue(widths, f"lipsește regula pentru {selector}")
            declared = " ".join(widths)
            self.assertIn("min-width", declared, selector)


class TestPopups(unittest.TestCase):
    """Popup-urile nu semănau între ele: patru lățimi, două mărimi de titlu, jumătate fără linie."""

    # lista care apare la hover peste desktop-uri nu e un popup cu date: are lățimea ei
    ALLOWED = {".desktops-hover"}

    def test_they_share_one_minimum_width(self):
        """
        Lățimea popup-ului însuși vine din jeton. Elementele dinăuntru (o iconiță de rând, o
        pastilă din systray) își au mărimea lor — ele nu hotărăsc cât de lat se deschide popup-ul.
        """
        written_by_hand = []
        for selectors, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", BODY):
            parts = [s.strip() for s in selectors.split(",") if s.strip()]
            # popup-ul însuși = o clasă singură, fără descendenți după spațiu
            if not parts or any(" " in part for part in parts):
                continue
            if not any(re.search(r"(popup|menu)", part) for part in parts):
                continue
            if set(parts) <= self.ALLOWED:
                continue
            for width in re.findall(r"min-width:\s*([0-9.]+px)", rule):
                written_by_hand.append(f"{parts[0]} -> {width}")
        self.assertEqual(written_by_hand, [], f"lățimi de popup scrise direct: {written_by_hand}")

    def test_the_data_popups_use_the_token(self):
        self.assertIn("min-width: var(--popup-w)", BODY)

    def test_every_popup_has_an_outline(self):
        block = re.search(r"\.cpu-popup, \.gpu-popup.*?\{(.*?)\}", BODY, re.S)
        self.assertIsNotNone(block)
        self.assertIn("border: 1px solid var(--line)", block.group(1))
        self.assertIn("border-radius: var(--r-popup)", block.group(1))

    @staticmethod
    def _paints_itself(name: str) -> bool:
        for selectors, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", BODY):
            parts = [s.strip() for s in selectors.split(",") if s.strip()]
            if name not in parts:
                continue  # regula e pentru altceva, sau pentru un descendent
            for value in re.findall(r"background(?:-color)?\s*:\s*([^;]+)", rule):
                if "transparent" not in value and "none" not in value.lower():
                    return True
        return False

    def test_every_popup_actually_has_a_background(self):
        """
        Testul de deasupra verifica doar ca regula comuna exista — nu si ca fiecare popup e
        trecut in ea. Asa au ajuns doua popup-uri noi fara niciun fundal: se vedea fereastra
        de dedesubt prin ele. Aici le numaram pe toate, una cate una.
        """
        shared = re.search(
            r"((?:\.[\w.-]+,\s*\n?)+\.[\w.-]+)\s*\{[^}]*background-color: rgba\(var\(--panel-rgb\)",
            BODY,
        )
        self.assertIsNotNone(shared, "nu mai gasesc regula comuna de fundal")
        listed = {c.strip() for c in shared.group(1).replace("\n", "").split(",")}

        # Panoul de sunet e transparent anume: panza lui isi deseneaza singura fundalul rotunjit
        # (audio_orbit_canvas.py). Orice alt popup transparent e o scapare.
        paints_its_own = {".audio-orbit-menu"}

        see_through = []
        for selectors, _rule in re.findall(r"([^{}]+)\{([^{}]*)\}", BODY):
            for part in (s.strip() for s in selectors.split(",")):
                match = re.fullmatch(r"\.([\w-]*(?:popup|menu|panel)[\w-]*)", part)
                if not match:
                    continue
                name = "." + match.group(1)
                if name in listed:
                    continue
                # Fundalul trebuie sa fie pe popup-ul insusi, nu pe ceva dinauntru, si sa fie
                # un fundal adevarat: „transparent” pe cutia interioara nu acopera nimic.
                if name not in paints_its_own and not self._paints_itself(name):
                    see_through.append(name)
        self.assertEqual(
            sorted(set(see_through)), [], f"popup-uri fara fundal (se vede prin ele): {sorted(set(see_through))}"
        )

    def test_titles_are_declared_once(self):
        titles = re.findall(r"font-size: var\(--fs-lead\);\n    font-weight: 700;", BODY)
        self.assertGreaterEqual(len(titles), 1)


class TestNoContradictions(unittest.TestCase):
    """
    Două reguli care se bat între ele înseamnă că una e moartă.

    Ceasul avea min-width: 150px într-un loc și min-width: 0 în altul, mai jos. Câștiga a
    doua, deci prima nu făcea nimic — dar arăta ca și cum ceasul ar rezerva 150 px, și chiar
    eu m-am luat după ea. Mai rău: dacă s-ar fi șters regula de jos, cei 150 px s-ar fi întors
    pe tăcute, fără ca nimeni să schimbe ceva cu intenție.
    """

    # proprietăți unde o a doua declarație pe același selector e aproape sigur o scăpare
    WATCHED = ("min-width", "max-width", "min-height", "max-height", "font-size", "border-radius")

    def declarations(self) -> dict[tuple[str, str], list[str]]:
        """
        Numai regulile scrise pentru un singur selector.

        O regulă de grup („iconița și eticheta au 11px”) urmată de una anume („iconița are
        12px”) e felul normal de a scrie CSS, nu o contradicție. Problema e când același
        selector, singur, primește aceeași proprietate de două ori, în două locuri diferite:
        atunci una dintre ele nu face nimic, și nu se vede care.
        """
        found: dict[tuple[str, str], list[str]] = {}
        for selectors, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", BODY):
            parts = [s.strip() for s in selectors.split(",") if s.strip()]
            if len(parts) != 1:
                continue
            for prop in self.WATCHED:
                for match in re.finditer(rf"(?:^|;)\s*{prop}\s*:\s*([^;]+)", rule):
                    found.setdefault((parts[0], prop), []).append(match.group(1).strip())
        return found

    def test_no_property_is_declared_twice_with_different_values(self):
        clashes = []
        for (selector, prop), values in self.declarations().items():
            if len(set(values)) > 1:
                clashes.append(f"{selector} -> {prop}: {values}")
        self.assertEqual(clashes, [], "reguli care se contrazic (una dintre ele e moartă):\n  " + "\n  ".join(clashes))

    def test_the_check_actually_reads_the_file(self):
        self.assertGreater(len(self.declarations()), 20)


class TestIconFamily(unittest.TestCase):
    """
    Glifele scrise în config.yaml vin dintr-o singură familie.

    Fontul barei (JetBrainsMono Nerd Font) strânge mai multe seturi de iconițe la un loc, iar
    ele au grosimi de linie diferite: două glife vecine din seturi diferite se văd ca fiind
    una mai subțire decât cealaltă. În config.yaml le putem ține pe toate într-un set.

    Excepția e documentată în schema net_status: acolo setul Material Design e ales anume,
    pentru că Font Awesome n-are perechi pornit/oprit pentru Wi-Fi și Bluetooth.
    """

    CONFIG = (CONFIG_DIR / "config.yaml").read_text(encoding="utf-8")

    @staticmethod
    def family(codepoint: int) -> str:
        if 0xF000 <= codepoint <= 0xF2FF:
            return "Font Awesome"
        if 0xF0001 <= codepoint <= 0xF1AF0:
            return "Material Design"
        if 0xE700 <= codepoint <= 0xEBFF:
            return "Segoe / Devicons"
        return f"U+{codepoint:04X}"

    def glyph_families(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for match in re.finditer(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})", self.CONFIG):
            codepoint = int(match.group(1) or match.group(2), 16)
            if codepoint < 0xE000:
                continue  # text obișnuit (liniuțe, semne), nu o glifă
            name = self.family(codepoint)
            found[name] = found.get(name, 0) + 1
        for char in self.CONFIG:
            if 0xE000 <= ord(char) <= 0xFFFFF:
                name = self.family(ord(char))
                found[name] = found.get(name, 0) + 1
        return found

    def test_config_uses_one_family(self):
        families = self.glyph_families()
        self.assertEqual(
            sorted(families),
            ["Font Awesome"],
            f"glife din familii amestecate în config.yaml: {families}",
        )

    def test_there_are_actually_glyphs_to_check(self):
        self.assertGreater(sum(self.glyph_families().values()), 10)


class TestColoursStillResolve(unittest.TestCase):
    def test_every_token_used_is_defined(self):
        missing = sorted(css_used_names(STYLES) - css_defined_names(STYLES, PALETTE))
        self.assertEqual(missing, [], f"jetoane folosite dar nedefinite: {missing}")

    def test_the_size_tokens_are_all_used(self):
        defined = {n for n in re.findall(r"--((?:fs|ic|r|pill|popup)[\w-]*)\s*:", TOKENS)}
        used = css_used_names(STYLES)
        unused = sorted(defined - used)
        self.assertEqual(unused, [], f"jetoane definite dar nefolosite nicăieri: {unused}")


if __name__ == "__main__":
    unittest.main()
