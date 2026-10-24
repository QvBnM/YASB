"""
yasb_patch.py - small, idempotent tweaks to YASB's own source (run by setup.ps1).

    py -3.14 yasb_patch.py C:\\path\\to\\yasb

1. main.py: qasync picks the FIRST Qt binding it can import (PyQt5 before PyQt6). On a PC
   that also has PyQt5 (installed by another program), YASB then runs PyQt6 widgets on a
   PyQt5 event loop: two Qt worlds, nothing ever starts and the bar never appears.
   QT_API=pyqt6, set before qasync is imported, pins it to YASB's own PyQt6.

2. bar.py: the bar is a 3-column grid (left / center / right) without column stretch,
   so the center column sits in the middle only when left and right are equally wide.
   Giving the two side columns the same stretch keeps the center (the clock) exactly
   in the middle of the screen, whatever the sides contain.

Codul de ieșire: 0 daca peticul din main.py e la locul lui (pus acum sau de la o instalare de
dinainte), 1 daca nu s-a putut aplica. Fara el, bara poate sa nu porneasca deloc, asa ca
instalarea se opreste; centrarea ceasului e doar frumoasa, deci nu opreste nimic.
"""

import sys
from pathlib import Path

MARKER = "# yasb-rice: equal side columns"
ANCHOR = "        self.bar_frame.setLayout(bar_layout)\n"
PATCH = (
    f"        {MARKER} keep the center section in the middle of the bar\n"
    "        bar_layout.setColumnStretch(0, 1)\n"
    "        bar_layout.setColumnStretch(1, 0)\n"
    "        bar_layout.setColumnStretch(2, 1)\n"
)


def patch_bar(yasb: Path) -> tuple[str, bool]:
    bar = yasb / "src" / "core" / "bar.py"
    raw = bar.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if MARKER in text:
        return "bar.py: already patched", True
    if text.count(ANCHOR) != 1:
        return "bar.py: anchor not found (YASB changed?) - clock centering not applied", False
    text = text.replace(ANCHOR, PATCH + ANCHOR)
    if crlf:
        text = text.replace("\n", "\r\n")
    bar.write_bytes(text.encode("utf-8"))
    return "bar.py: patched (clock always centered)", True


MAIN_MARKER = "# yasb-rice: qasync must use PyQt6"
MAIN_ANCHOR = "import qasync"
MAIN_PATCH = (
    f"import os  {MAIN_MARKER}\n"
    'os.environ["QT_API"] = "pyqt6"  # otherwise qasync takes PyQt5 if another program installed it\n'
    "\n"
)


def patch_main(yasb: Path) -> tuple[str, bool]:
    main = yasb / "src" / "main.py"
    raw = main.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if MAIN_MARKER in text:
        return "main.py: already patched", True
    lines = text.split("\n")
    idx = next((i for i, ln in enumerate(lines) if ln.startswith(MAIN_ANCHOR)), None)
    if idx is None:
        return "main.py: 'import qasync' not found (YASB changed?) - QT_API not set", False
    lines.insert(idx, MAIN_PATCH.rstrip("\n"))
    text = "\n".join(lines)
    if crlf:
        text = text.replace("\n", "\r\n")
    main.write_bytes(text.encode("utf-8"))
    return "main.py: patched (qasync uses PyQt6)", True


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    yasb = Path(sys.argv[1])
    bar_message, _bar_ok = patch_bar(yasb)  # ceasul centrat: frumos, dar nu opreste bara
    main_message, main_ok = patch_main(yasb)
    print(bar_message)
    print(main_message)
    return 0 if main_ok else 1


if __name__ == "__main__":
    sys.exit(main())
