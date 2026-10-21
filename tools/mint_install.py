"""
Instaleaza Mint Bar v2 peste o copie YASB rulata din sursa (acolo unde stau deja
widget-urile tale: src/core/widgets/yasb/).

    python tools\\mint_install.py --yasb C:\\cale\\catre\\yasb
    python tools\\mint_install.py --yasb C:\\cale\\catre\\yasb --config-only
    python tools\\mint_install.py --yasb C:\\cale\\catre\\yasb --dry-run

Ce face:
  1. copiaza widget-urile noi si schemele lor in src/ (nu atinge alte fisiere);
  2. inregistreaza sursa "bar_commands" in lansatorul YASB (quick_launch), in cele 3 locuri
     descrise in providers/example.py; ruleaza de cate ori vrei, nu dubleaza nimic;
  3. pune config.yaml si styles.css noi in folderul de configurare, cu copie de rezerva
     (config.yaml.bak-AAAALLZZ-HHMM). palette.css nu e atins: il scrie generatorul tau.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
PKG_SRC = os.path.join(PKG, "src")  # setup package layout: src/ next to tools/
PKG_CONFIG = os.path.join(PKG, "config")

MARK = "# mint-bar"

PROVIDER_CONFIG = f'''

{MARK}: comenzile barei in lansator (providers/bar_commands.py)
class BarCommandItem(CustomBaseModel):
    title: str
    description: str = ""
    icon: str = ""
    keywords: str = ""
    widget: str = ""
    callback: str = ""
    exec: str = ""


class BarCommandsProviderConfig(CustomBaseModel):
    enabled: bool = False
    prefix: str = "*"
    priority: int = 0
    commands: list[BarCommandItem] = []

'''


def say(msg: str) -> None:
    print(msg, flush=True)


def patch_text(path: str, edits: list[tuple[str, str, str]], dry: bool) -> bool:
    """edits = (ancora, text_de_inserat, 'before'|'after'). Sare peste ce exista deja."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    original = text
    nl = "\r\n" if "\r\n" in text else "\n"  # pastram sfarsiturile de linie ale fisierului
    for anchor, insert, where in edits:
        anchor, insert = anchor.replace("\n", nl), insert.replace("\n", nl)
        if insert.strip() in text:
            continue
        if anchor not in text:
            raise SystemExit(f"Nu gasesc locul de inserat in {path}:\n  {anchor!r}\nVersiunea YASB e prea diferita.")
        text = text.replace(anchor, insert + anchor if where == "before" else anchor + insert, 1)
    if text != original:
        if not dry:
            if not os.path.exists(path + ".mint-bak"):
                shutil.copy2(path, path + ".mint-bak")  # originalul, o singura data
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        return True
    return False


def install_src(yasb: str, dry: bool) -> None:
    dst_src = os.path.join(yasb, "src")
    if not os.path.isdir(os.path.join(dst_src, "core", "widgets", "yasb")):
        raise SystemExit(f"{yasb} nu pare o copie YASB din sursa (lipseste src/core/widgets/yasb).")
    copied = 0
    for root, _dirs, files in os.walk(PKG_SRC):
        for name in files:
            if not name.endswith(".py"):
                continue
            src = os.path.join(root, name)
            rel = os.path.relpath(src, PKG_SRC)
            dst = os.path.join(dst_src, rel)
            if not dry:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            copied += 1
            say(f"  + src/{rel.replace(os.sep, '/')}")
    say(f"{copied} fisiere copiate in src/.")

    ql = os.path.join(dst_src, "core", "widgets", "services", "quick_launch")
    changed = []
    if patch_text(
        os.path.join(ql, "providers", "__init__.py"),
        [("from .binance import *", f"from .bar_commands import *  {MARK}\n", "before")],
        dry,
    ):
        changed.append("providers/__init__.py")
    if patch_text(
        os.path.join(ql, "service.py"),
        [
            (
                "from core.widgets.services.quick_launch.workers import",
                f"from core.widgets.services.quick_launch.providers.bar_commands import BarCommandsProvider  {MARK}\n",
                "before",
            ),
            ('    "apps": AppsProvider,\n', f'    "bar_commands": BarCommandsProvider,  {MARK}\n', "after"),
        ],
        dry,
    ):
        changed.append("quick_launch/service.py")
    if patch_text(
        os.path.join(dst_src, "core", "validation", "widgets", "yasb", "quick_launch.py"),
        [
            ("class QuickLaunchProvidersConfig(CustomBaseModel):", PROVIDER_CONFIG.lstrip("\n"), "before"),
            (
                "    apps: AppsProviderConfig = AppsProviderConfig()\n",
                f"    bar_commands: BarCommandsProviderConfig = BarCommandsProviderConfig()  {MARK}\n",
                "after",
            ),
        ],
        dry,
    ):
        changed.append("validation/quick_launch.py")
    say("Lansator: " + (", ".join(changed) + " actualizate." if changed else "comenzile barei erau deja inregistrate."))


def config_dir(arg: str | None) -> str:
    if arg:
        return arg
    return os.getenv("YASB_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config", "yasb")


def install_config(target: str, dry: bool) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    os.makedirs(target, exist_ok=True)
    for name in ("config.yaml", "styles.css"):
        src = os.path.join(PKG_CONFIG, name)
        dst = os.path.join(target, name)
        if os.path.exists(dst):
            backup = f"{dst}.bak-{stamp}"
            if not dry:
                shutil.copy2(dst, backup)
            say(f"  copie de rezerva: {os.path.basename(backup)}")
        if not dry:
            shutil.copy2(src, dst)
        say(f"  + {name}")
    if not os.path.exists(os.path.join(target, "palette.css")):
        if not dry:
            shutil.copy2(os.path.join(PKG_CONFIG, "palette.css"), os.path.join(target, "palette.css"))
        say("  + palette.css (exemplu; il rescrie generatorul tau)")
    say(f"Configurare in {target}.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Instaleaza Mint Bar v2 peste YASB.")
    ap.add_argument("--yasb", help="folderul YASB (cel care contine src/)")
    ap.add_argument("--config", help="folderul de configurare (implicit ~/.config/yasb sau YASB_CONFIG_HOME)")
    ap.add_argument("--config-only", action="store_true", help="doar config.yaml si styles.css")
    ap.add_argument("--src-only", action="store_true", help="doar widget-urile, fara configurare")
    ap.add_argument("--dry-run", action="store_true", help="arata ce s-ar face, fara sa scrie nimic")
    args = ap.parse_args()

    if not args.config_only:
        if not args.yasb:
            ap.error("--yasb e necesar (sau foloseste --config-only)")
        say("Widget-uri:")
        install_src(os.path.abspath(args.yasb), args.dry_run)
    if not args.src_only:
        say("Configurare:")
        install_config(config_dir(args.config), args.dry_run)
    say("Gata. Reporneste YASB." if not args.dry_run else "Simulare terminata, nimic scris.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
