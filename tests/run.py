"""
Rulează toate testele barei.

    python tests/run.py           # toate
    python tests/run.py layout    # doar un fișier (test_layout.py)

Nu are nevoie de Windows, de PyQt6 sau de pytest: logica se testează pe module înlocuitoare
(tests/stubs.py). Ce NU acoperă: desenarea propriu-zisă, apelurile către Windows și COM.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(HERE))
    pattern = f"test_{argv[0]}.py" if argv else "test_*.py"
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern=pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
