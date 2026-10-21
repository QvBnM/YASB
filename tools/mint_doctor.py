"""
mint_doctor.py - verifică totul înainte ca bara să pornească, și spune exact ce nu se potrivește.

    py -3.14 tools\\mint_doctor.py --yasb C:\\cale\\catre\\yasb
    py -3.14 tools\\mint_doctor.py                 # doar ce se poate verifica fără YASB
    py -3.14 tools\\mint_doctor.py --config C:\\alt\\folder\\yasb

Iese cu 0 dacă totul e în regulă și cu 1 dacă ceva ar strica bara. setup.ps1 se oprește
la 1, deci o instalare care ar pica nu mai ajunge să pornească.

Ce verifică:
  1. versiunea de Python și de YASB (fixată în tools/yasb-pin.txt);
  2. contractul cu YASB: fiecare lucru din interiorul lor pe care ne sprijinim chiar există;
  3. config.yaml: fiecare widget numit într-o regulă există, fiecare opțiune trece prin schema ei;
  4. styles.css: fiecare culoare folosită e definită în paletă;
  5. fontul, HWiNFO și RivaTuner (doar de știut, nu opresc nimic).
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mint_check import (  # noqa: E402
    CONFIG_DIR,
    SRC,
    Report,
    contract_problems,
    css_used_names,
    hardcoded_colours,
    load_config,
    missing_references,
    placed_widgets,
    scan_yasb_imports,
    unresolved_css_vars,
    unused_css_vars,
    widgets_placed_twice,
)

PIN_FILE = HERE / "yasb-pin.txt"
UNPINNED = "unpinned"

# Widget-uri definite în config dar nepuse în nicio bară, în mod intenționat.
KNOWN_UNPLACED = {"speedtest"}


# ===================================================================== pin


def read_pin() -> str:
    try:
        for line in PIN_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except OSError:
        pass
    return UNPINNED


def write_pin(commit: str) -> None:
    PIN_FILE.write_text(
        "# Commit-ul YASB pe care bara a fost verificată. Instalarea rămâne pe el.\n"
        "# Se schimbă doar rulând setup.ps1 cu -YasbRef <ramura-sau-commit>.\n"
        f"{commit}\n",
        encoding="utf-8",
    )


def git_commit(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# ===================================================================== verificări


def check_python() -> Report:
    r = Report("Python")
    major, minor = sys.version_info[:2]
    r.note(f"Python {major}.{minor}")
    if (major, minor) < (3, 12):
        r.problem(f"Bara cere Python 3.12 sau mai nou; aici e {major}.{minor}.")
    return r


def check_yasb_version(yasb: Path | None) -> Report:
    r = Report("Versiunea YASB")
    pin = read_pin()
    if yasb is None:
        r.note("YASB nu a fost dat (--yasb): verificarea versiunii s-a sărit")
        return r
    if not (yasb / "src" / "main.py").exists():
        r.problem(f"{yasb} nu pare o copie YASB din sursă (lipsește src/main.py).")
        return r
    commit = git_commit(yasb)
    if commit is None:
        r.note("Copia YASB nu e un depozit git: nu pot verifica pe ce versiune e.")
        return r
    if pin == UNPINNED:
        r.note(f"Încă nefixat. După o instalare reușită, versiunea {commit[:10]} devine cea fixată.")
        return r
    r.note(f"fixat pe {pin[:10]}, instalat {commit[:10]}")
    if commit != pin:
        r.problem(
            f"YASB e pe alt commit decât cel verificat: {commit[:10]} în loc de {pin[:10]}.\n"
            f"        Fie îl aduci înapoi (git -C {yasb} checkout {pin[:10]}),\n"
            f"        fie rulezi setup.ps1 cu -YasbRef ca să fixezi conștient versiunea nouă."
        )
    return r


def check_contract(yasb: Path | None) -> Report:
    """Fiecare lucru din interiorul YASB pe care ne sprijinim chiar există?"""
    r = Report("Contractul cu YASB")
    if yasb is None:
        r.note("YASB nu a fost dat (--yasb): contractul nu s-a putut verifica")
        return r
    src = yasb / "src"
    if not src.is_dir():
        r.problem(f"{src} nu există: nu pot citi codul YASB.")
        return r
    imports = scan_yasb_imports()
    r.note(f"{len(imports)} module YASB folosite de bară, citite fără să fie pornite")
    problems, notes = contract_problems(src)
    for item in notes:
        r.note(item)
    for item in problems:
        r.problem(item)
    if not problems:
        r.note("toate numele pe care ne sprijinim sunt la locul lor")
    if notes:
        r.note("Rulează doctorul cu aceeași versiune de Python cu care pornește bara (py -3.14).")
    return r


def check_config(cfg: dict, yasb: Path | None) -> Report:
    r = Report("config.yaml")
    widgets = cfg.get("widgets", {}) or {}
    r.note(f"{len(widgets)} widget-uri configurate")

    for item in missing_references(cfg):
        r.problem(f"widget numit dar inexistent: {item}")
    for item in widgets_placed_twice(cfg):
        r.problem(f"widget pus de două ori: {item}")

    unplaced = sorted(set(widgets) - placed_widgets(cfg) - KNOWN_UNPLACED)
    if unplaced:
        r.note(f"definite dar nepuse în nicio bară (deci nu rulează): {', '.join(unplaced)}")

    if yasb is None:
        r.note("Schemele nu s-au verificat: ele cer YASB (--yasb)")
        return r

    for path in (yasb / "src", SRC):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    # Dacă nici măcar un widget nu se poate încărca, lipsesc dependențele (PyQt6 & co.),
    # nu e vina configurării. Un singur mesaj, nu câte unul pentru fiecare widget.
    try:
        importlib.import_module("core.widgets.yasb.responsive")
    except Exception as exc:
        r.note(
            f"Schemele nu s-au verificat: codul barei nu se poate încărca aici "
            f"({type(exc).__name__}: {exc}). Rulează doctorul pe calculatorul cu YASB instalat."
        )
        return r

    checked = 0
    for name, widget in widgets.items():
        kind = widget.get("type", "")
        if not kind.startswith("yasb."):
            continue
        module_name = "core.widgets.yasb." + kind.split(".")[1]
        try:
            module = importlib.import_module(module_name)
            schema = getattr(getattr(module, kind.split(".")[2]), "validation_schema", None)
        except Exception as exc:
            r.problem(f"{name}: nu pot încărca {kind} ({type(exc).__name__}: {exc})")
            continue
        if schema is None:
            continue
        try:
            schema(**((widget.get("options") or {})))
            checked += 1
        except Exception as exc:
            r.problem(f"{name} ({kind}): opțiuni respinse\n        {exc}")
    r.note(f"{checked} widget-uri au trecut prin schemele lor")
    return r


def check_styles(config_dir: Path) -> Report:
    r = Report("styles.css")
    styles_path = config_dir / "styles.css"
    palette_path = config_dir / "palette.css"
    if not styles_path.exists():
        r.problem(f"lipsește {styles_path}")
        return r
    styles = styles_path.read_text(encoding="utf-8")
    palette = palette_path.read_text(encoding="utf-8") if palette_path.exists() else ""
    if not palette:
        r.problem(f"lipsește {palette_path} (o scrie yasb_palette.py din wallpaper)")

    missing = unresolved_css_vars(styles, palette)
    if missing:
        r.problem("culori folosite în stiluri dar nedefinite în paletă: " + ", ".join(missing))

    hexes = hardcoded_colours(styles)
    if hexes:
        r.problem("culori scrise direct în styles.css (nu se mai schimbă cu wallpaper-ul): " + ", ".join(hexes))

    unused = unused_css_vars(styles, palette)
    if unused:
        r.note("calculate în paletă dar nefolosite nicăieri: " + ", ".join(unused))
    if not missing:
        r.note(f"{len(css_used_names(styles))} culori folosite, toate rezolvate din paletă")
    return r


def check_tools() -> Report:
    """Programele de care depind unele widget-uri. Lipsa lor ascunde widget-ul, nu strică bara."""
    r = Report("Programe ajutătoare")
    if os.name != "nt":
        r.note("Nu rulez pe Windows: fontul, HWiNFO și RivaTuner nu se pot verifica aici.")
        return r

    import ctypes

    def mapping_exists(name: str) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenFileMappingW.restype = ctypes.c_void_p
        kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        handle = kernel32.OpenFileMappingW(0x0004, 0, name)
        if handle:
            ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(handle))
            return True
        return False

    font_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
    system_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    has_font = any(
        p.exists() and any(p.glob("JetBrainsMonoNerdFont*.ttf")) for p in (font_dir, system_fonts)
    )
    if not has_font:
        r.problem("Fontul JetBrainsMono Nerd Font nu e instalat: bara va arăta cu alt font și alte lățimi.")
    else:
        r.note("Font JetBrainsMono Nerd Font: instalat")

    r.note("HWiNFO (temperatura procesorului): " + ("pornit" if mapping_exists("Global\\HWiNFO_SENS_SM2") else "oprit"))
    r.note("RivaTuner (FPS în jocuri): " + ("pornit" if mapping_exists("RTSSSharedMemoryV2") else "oprit"))
    return r


# ===================================================================== raport


def print_report(reports: list[Report]) -> bool:
    width = 72
    print("=" * width)
    print("  Controlul barei")
    print("=" * width)
    ok = True
    for report in reports:
        mark = "OK  " if report.ok else "STOP"
        print(f"\n[{mark}] {report.name}")
        for note in report.notes:
            if note:
                print(f"       {note}")
        for problem in report.problems:
            ok = False
            print(f"   ->  {problem}")
    print("\n" + "-" * width)
    if ok:
        print("Totul e în regulă: bara poate porni.")
    else:
        print("Instalarea se oprește. Reparați punctele marcate cu -> și rulați din nou.")
    print("-" * width)
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verifică bara înainte de instalare.")
    ap.add_argument("--yasb", help="folderul YASB (cel care conține src/)")
    ap.add_argument("--config", help="folderul de configurare (implicit cel din acest depozit)")
    ap.add_argument("--record-pin", action="store_true", help="fixează versiunea YASB de acum ca fiind cea bună")
    args = ap.parse_args(argv)

    yasb = Path(args.yasb).resolve() if args.yasb else None
    config_dir = Path(args.config).resolve() if args.config else CONFIG_DIR

    try:
        cfg = load_config(config_dir / "config.yaml")
    except Exception as exc:
        print(f"Nu pot citi {config_dir / 'config.yaml'}: {exc}")
        return 1

    reports = [
        check_python(),
        check_yasb_version(yasb),
        check_contract(yasb),
        check_config(cfg, yasb),
        check_styles(config_dir),
        check_tools(),
    ]
    ok = print_report(reports)

    if ok and args.record_pin and yasb is not None:
        commit = git_commit(yasb)
        if commit:
            write_pin(commit)
            print(f"Versiunea YASB {commit[:10]} e acum cea fixată.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
