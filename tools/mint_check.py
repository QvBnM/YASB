"""
Verificările comune ale barei, într-un singur loc.

Le folosesc și testele (tests/test_config.py), și doctorul (tools/mint_doctor.py), ca să nu
existe două adevăruri despre ce înseamnă „configurarea e în regulă”.

Nimic de aici nu are nevoie de Windows, de PyQt6 sau de YASB instalat: se uită doar la
fișierele din acest depozit.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
CONFIG_DIR = REPO / "config"


# ===================================================================== rezultate


@dataclass
class Report:
    """Ce a găsit o verificare: probleme (opresc instalarea) și observații (doar de știut)."""

    name: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def problem(self, text: str) -> None:
        self.problems.append(text)

    def note(self, text: str) -> None:
        self.notes.append(text)


# ===================================================================== config.yaml


def load_config(path: Path | None = None) -> dict:
    import yaml

    return yaml.safe_load((path or CONFIG_DIR / "config.yaml").read_text(encoding="utf-8")) or {}


def _options(cfg: dict, name: str) -> dict:
    return (cfg.get("widgets", {}).get(name, {}) or {}).get("options", {}) or {}


def referenced_widget_names(cfg: dict) -> dict[str, list[str]]:
    """
    Fiecare loc din config care numește alte widget-uri -> numele numite.

    Asta prinde clasa de greșeli care azi trece în tăcere: un nume scris greșit într-o regulă
    nu face nimic și nu scrie nimic în jurnal, regula pur și simplu nu se aplică niciodată.
    """
    out: dict[str, list[str]] = {}
    widgets = cfg.get("widgets", {}) or {}

    for bar_name, bar in (cfg.get("bars") or {}).items():
        for column, items in (bar.get("widgets") or {}).items():
            out[f"bars.{bar_name}.{column}"] = list(items or [])

    for name, widget in widgets.items():
        kind = widget.get("type", "")
        opts = _options(cfg, name)
        if kind.endswith("grouper.GrouperWidget"):
            out[f"{name}.widgets"] = list(opts.get("widgets") or [])
        elif kind.endswith("context_mode.ContextModeWidget"):
            out[f"{name}.hidden_by_default"] = list(opts.get("hidden_by_default") or [])
            for mode in opts.get("modes") or []:
                label = mode.get("name", "?")
                out[f"{name}.{label}.hide"] = list(mode.get("hide") or [])
                out[f"{name}.{label}.show"] = list(mode.get("show") or [])
        elif kind.endswith("responsive.ResponsiveWidget"):
            out[f"{name}.hide_left"] = list(opts.get("hide_left") or [])
            out[f"{name}.hide_right"] = list(opts.get("hide_right") or [])
            out[f"{name}.flexible"] = list((opts.get("flexible") or {}).keys())
        elif kind.endswith("mint_thresholds.MintThresholdsWidget"):
            out[f"{name}.rules"] = [r["widget"] for r in opts.get("rules") or [] if "widget" in r]
        elif kind.endswith("cover_accent.CoverAccentWidget"):
            out[f"{name}.targets"] = list(opts.get("targets") or [])
        elif kind.endswith("bar_notifications.BarNotificationsWidget"):
            if opts.get("replace"):
                out[f"{name}.replace"] = [opts["replace"]]
        elif kind.endswith("quick_launch.QuickLaunchWidget"):
            commands = ((opts.get("providers") or {}).get("bar_commands") or {}).get("commands") or []
            out[f"{name}.bar_commands"] = [c["widget"] for c in commands if c.get("widget")]
    return out


def missing_references(cfg: dict) -> list[str]:
    known = set(cfg.get("widgets", {}) or {})
    return [
        f"{where} -> '{name}'"
        for where, names in referenced_widget_names(cfg).items()
        for name in names
        if name not in known
    ]


def placed_widgets(cfg: dict) -> set[str]:
    """Widget-urile care chiar ajung într-o bară (direct sau printr-un grup)."""
    placed: set[str] = set()
    for bar in (cfg.get("bars") or {}).values():
        for items in (bar.get("widgets") or {}).values():
            placed.update(items or [])
    for name, widget in (cfg.get("widgets", {}) or {}).items():
        if widget.get("type", "").endswith("grouper.GrouperWidget"):
            placed.update(_options(cfg, name).get("widgets") or [])
    return placed


def widgets_placed_twice(cfg: dict) -> list[str]:
    seen: dict[str, str] = {}
    twice: list[str] = []
    for bar_name, bar in (cfg.get("bars") or {}).items():
        for column, items in (bar.get("widgets") or {}).items():
            for name in items or []:
                where = f"bars.{bar_name}.{column}"
                if name in seen:
                    twice.append(f"'{name}' ({seen[name]} și {where})")
                seen[name] = where
    return twice


# ===================================================================== styles.css

_VAR_USED = re.compile(r"var\(\s*--([\w-]+)\s*\)")
_VAR_DEFINED = re.compile(r"--([\w-]+)\s*:")
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _without_comments(css: str) -> str:
    """Un nume scris într-un comentariu nu e nici folosit, nici definit."""
    return _COMMENT.sub("", css)


def css_defined_names(styles: str, palette: str) -> set[str]:
    """Culorile pe care le poate folosi styles.css: din paletă + rezervele dinaintea importului."""
    styles = _without_comments(styles)
    names = set(_VAR_DEFINED.findall(_without_comments(palette)))
    names |= set(_VAR_DEFINED.findall(styles.split("@import", 1)[0]))
    names |= {f"{n}-rgb" for n in names}  # generatorul scrie și varianta „r, g, b”
    return names


def css_used_names(styles: str) -> set[str]:
    return set(_VAR_USED.findall(_without_comments(styles)))


def unresolved_css_vars(styles: str, palette: str) -> list[str]:
    return sorted(css_used_names(styles) - css_defined_names(styles, palette))


def unused_css_vars(styles: str, palette: str) -> list[str]:
    """Culori calculate de generator dar nefolosite nicăieri: paleta și stilurile s-au depărtat."""
    defined = {n for n in css_defined_names(styles, palette) if not n.endswith("-rgb")}
    used = {n.removesuffix("-rgb") for n in css_used_names(styles)}
    return sorted(defined - used)


def hardcoded_colours(styles: str) -> list[str]:
    """Culorile vin din wallpaper: un hex scris direct în stiluri nu s-ar mai schimba cu paleta."""
    body = styles.split("@import", 1)[-1]
    return _HEX.findall(_COMMENT.sub("", body))


# ===================================================================== contractul cu YASB


def _is_ours(module: str) -> bool:
    """Modulele noastre stau în acest depozit; restul vin din YASB."""
    return (SRC / (module.replace(".", "/") + ".py")).exists()


def scan_yasb_imports(src: Path | None = None) -> dict[str, set[str]]:
    """
    Ce anume împrumutăm din YASB, citit din propriul nostru cod.

    Lista nu se scrie de mână, deci nu poate rămâne în urmă: dacă mâine un widget nou importă
    altceva din YASB, apare aici singur și doctorul îl verifică de la prima rulare.
    """
    used: dict[str, set[str]] = {}
    for path in sorted((src or SRC).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("core."):
                if _is_ours(node.module):
                    continue
                # „from core.widgets.yasb import mint_visibility” ia un modul al nostru dintr-un
                # pachet YASB: pachetul e al lor, modulul e al nostru, deci nu e de verificat.
                names = {alias.name for alias in node.names if not _is_ours(f"{node.module}.{alias.name}")}
                if names:
                    used.setdefault(node.module, set()).update(names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("core.") and not _is_ours(alias.name):
                        used.setdefault(alias.name, set())
    return used


# Lucrurile din interiorul YASB pe care ne sprijinim fără să le importăm: atribute și metode.
# Astea sunt partea fragilă — un import lipsă se vede imediat, un atribut lipsă apare abia
# când folosești funcția. Fiecare rând se recitește când se schimbă versiunea YASB.
CONTRACT_ATTRIBUTES: dict[str, dict[str, list[str]]] = {
    "core.widgets.base": {
        "BaseWidget": [
            "_init_container",
            "build_widget_label",
            "register_callback",
            # il folosesc comenzile barei din lansator ca sa apese pe un widget din afara lui
            "_run_callback",
        ],
    },
    "core.widgets.yasb.windows_desktops": {
        "WorkspaceWidget": ["_svc", "workspace_buttons", "_update_button"],
        "WorkspaceButton": ["workspace_index"],
    },
    "core.widgets.yasb.pomodoro": {
        "PomodoroWidget": ["_shared_state", "_instances"],
    },
    "core.widgets.yasb.clock": {
        "CustomCalendar": ["paintCell"],
    },
    "core.widgets.yasb.audio_visualizer": {
        "AudioVisualizerWidget": [
            "_idle_hidden",
            "_fade_timer",
            "_reset_visual",
            "_apply_collapsed",
            "_on_audio_started",
            "_on_frame",
        ],
    },
    "core.widgets.yasb.active_window": {
        "ActiveWindowWidget": ["_window_title_text"],
    },
    "core.widgets.services.windows_desktops.service": {
        "WindowsDesktopService": ["switch_desktop", "get_desktops", "get_current_desktop"],
    },
    "core.widgets.services.volume.service": {
        "AudioOutputService": [
            "register_widget",
            "unregister_widget",
            "get_volume_interface",
            "get_default_device_id",
            "get_all_devices",
        ],
    },
    "core.widgets.services.microphone.service": {
        "AudioInputService": ["register_widget", "unregister_widget", "get_microphone_interface"],
    },
    "core.widgets.services.taskbar.application_window": {
        "ApplicationWindow": ["is_taskbar_window", "process_pid", "process_name", "process_path", "title", "update"],
    },
    "core.events.service": {
        "EventService": ["register_event", "unregister_event", "emit_event"],
    },
}

# Funcții din module YASB pe care le chemăm fără să le importăm la început de fișier.
CONTRACT_MODULE_FUNCTIONS: dict[str, list[str]] = {
    "core.widgets.yasb.clock": ["_supported_country", "_get_cached_country_holidays"],
}


# ===================================================================== citirea codului YASB


class _Source:
    """
    Numele definite de codul YASB, citite din fișiere, fără să le execute.

    Nu pornim codul altcuiva doar ca să verificăm o listă de nume: citirea e sigură, merge
    și fără PyQt6 instalat, și dă același rezultat pe orice calculator.
    """

    def __init__(self, src: Path):
        self.src = src
        self._modules: dict[str, ast.Module | None] = {}
        self._unreadable: dict[str, str] = {}

    def module(self, dotted: str) -> ast.Module | None:
        if dotted not in self._modules:
            path = self.src / (dotted.replace(".", "/") + ".py")
            folder = self.src / dotted.replace(".", "/")
            if not path.exists():
                path = folder / "__init__.py"
            if not path.exists() and folder.is_dir():
                # pachet fără __init__.py: folderul însuși e modulul, nu are nume de verificat
                self._modules[dotted] = ast.Module(body=[], type_ignores=[])
                self._unreadable.pop(dotted, None)
                return self._modules[dotted]
            try:
                self._modules[dotted] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except OSError:
                self._modules[dotted] = None
            except SyntaxError as exc:
                # YASB e scris pentru Python 3.14; citit cu o versiune mai veche, unele fișiere
                # nu se pot analiza. Nu înseamnă că lipsesc.
                self._modules[dotted] = None
                self._unreadable[dotted] = f"linia {exc.lineno}: {exc.msg}"
        return self._modules[dotted]

    def exists(self, dotted: str) -> bool:
        self.module(dotted)
        return dotted in self._unreadable or self._modules.get(dotted) is not None

    def unreadable(self) -> dict[str, str]:
        """Fișiere care există dar nu s-au putut citi cu acest Python."""
        return dict(self._unreadable)

    def top_level_names(self, dotted: str) -> set[str]:
        tree = self.module(dotted)
        if tree is None:
            return set()
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        return names

    def _class_node(self, dotted: str, class_name: str) -> ast.ClassDef | None:
        tree = self.module(dotted)
        if tree is None:
            return None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return node
        return None

    def _bases(self, dotted: str, node: ast.ClassDef) -> list[tuple[str, str]]:
        """Clasele de bază care se pot găsi tot în codul YASB: (modul, nume)."""
        tree = self.module(dotted)
        imported: dict[str, str] = {}
        if tree is not None:
            for item in ast.walk(tree):
                if isinstance(item, ast.ImportFrom) and item.module:
                    for alias in item.names:
                        imported[alias.asname or alias.name] = item.module
        out = []
        for base in node.bases:
            name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
            if not name:
                continue
            out.append((imported.get(name, dotted), name))
        return out

    def class_members(self, dotted: str, class_name: str, _seen: set | None = None) -> set[str] | None:
        """Metodele și atributele unei clase, inclusiv cele moștenite din codul YASB."""
        seen = _seen if _seen is not None else set()
        key = (dotted, class_name)
        if key in seen:
            return set()
        seen.add(key)
        node = self._class_node(dotted, class_name)
        if node is None:
            return None
        members: set[str] = set()
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                members.add(item.name)
            elif isinstance(item, ast.Assign):
                members.update(t.id for t in item.targets if isinstance(t, ast.Name))
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                members.add(item.target.id)
        # atributele puse în __init__ si in restul metodelor: self.ceva = ...
        for item in ast.walk(node):
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        members.add(target.attr)
            elif (
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Attribute)
                and isinstance(item.target.value, ast.Name)
                and item.target.value.id == "self"
            ):
                members.add(item.target.attr)
        for base_module, base_name in self._bases(dotted, node):
            inherited = self.class_members(base_module, base_name, seen)
            if inherited:
                members |= inherited
        return members


def contract_problems(yasb_src: Path) -> tuple[list[str], list[str]]:
    """
    Ce anume din YASB nu mai e acolo unde bara se așteaptă.

    Întoarce (probleme, observații). Lista de probleme goală înseamnă că totul se potrivește.
    Fiecare rând e scris ca să poată fi citit direct de om: numele exact care lipsește, nu un
    traceback.
    """
    source = _Source(yasb_src)
    problems: list[str] = []
    imports = scan_yasb_imports()

    wanted = sorted(set(imports) | set(CONTRACT_ATTRIBUTES) | set(CONTRACT_MODULE_FUNCTIONS))
    for dotted in wanted:
        if not source.exists(dotted):
            problems.append(f"lipsește fișierul {dotted.replace('.', '/')}.py din YASB")
            continue
        if dotted in source.unreadable():
            continue  # fișierul e acolo, dar nu l-am putut citi: nu inventăm o problemă
        defined = source.top_level_names(dotted)
        for name in sorted(imports.get(dotted, set())):
            # „from core.widgets.yasb import clock” ia un modul din pachet, nu un nume din fișier
            if name not in defined and not source.exists(f"{dotted}.{name}"):
                problems.append(f"{dotted} nu mai are '{name}'")
        for func in CONTRACT_MODULE_FUNCTIONS.get(dotted, []):
            if func not in defined:
                problems.append(f"{dotted} nu mai are funcția '{func}()'")
        for class_name, attributes in CONTRACT_ATTRIBUTES.get(dotted, {}).items():
            members = source.class_members(dotted, class_name)
            if members is None:
                problems.append(f"{dotted} nu mai are clasa '{class_name}'")
                continue
            for attribute in attributes:
                if attribute not in members:
                    problems.append(f"{class_name} (din {dotted}) nu mai are '{attribute}'")

    notes = [
        f"{dotted}: nu l-am putut citi cu acest Python ({why}) — verificarea lui s-a sărit"
        for dotted, why in sorted(source.unreadable().items())
    ]
    return problems, notes
