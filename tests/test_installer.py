"""
Fișierul de instalare pentru dublu-click.

Un .bat se citește cu pagina de cod a consolei, nu cu UTF-8, iar cmd.exe se poartă ciudat cu
sfârșituri de linie Unix. Lucrurile astea nu se văd până nu dai dublu-click pe calculatorul
unde contează, deci le verificăm aici.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BAT = REPO / "instalare.bat"
SETUP = REPO / "setup.ps1"


class TestInstaller(unittest.TestCase):
    def setUp(self):
        self.raw = BAT.read_bytes()
        self.text = self.raw.decode("ascii", errors="replace")

    def test_it_exists_next_to_the_script_it_runs(self):
        self.assertTrue(BAT.exists())
        self.assertTrue(SETUP.exists())

    def test_it_is_plain_ascii(self):
        """Diacriticele dintr-un .bat depind de pagina de cod a consolei: nu ne bazăm pe ea."""
        try:
            self.raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"caracter care nu e ASCII în instalare.bat, la octetul {exc.start}")

    def test_it_has_windows_line_endings(self):
        self.assertGreater(self.raw.count(b"\r\n"), 20)
        lone = re.findall(rb"(?<!\r)\n", self.raw)
        self.assertEqual(lone, [], "sfârșituri de linie Unix într-un .bat")

    def test_it_has_no_byte_order_mark(self):
        """Un BOM la început face cmd.exe să se împiedice de prima linie."""
        self.assertNotEqual(self.raw[:3], b"\xef\xbb\xbf")

    def test_it_runs_the_real_script(self):
        self.assertIn("setup.ps1", self.text)
        self.assertIn("-ExecutionPolicy Bypass", self.text)

    def test_it_passes_your_options_through(self):
        """instalare.bat -YasbRef main trebuie să ajungă la script, nu să fie înghițit."""
        self.assertIn("%*", self.text)

    def test_it_works_from_anywhere(self):
        """Dublu-click din alt folder nu trebuie să îl încurce."""
        self.assertIn("%~dp0", self.text)

    def test_the_window_stays_open(self):
        """Altfel, dacă ceva se oprește, fereastra dispare înainte să apuci să citești."""
        self.assertIn("pause", self.text)

    def test_it_hands_back_the_exit_code(self):
        self.assertIn("exit /b", self.text)

    def test_it_refuses_to_run_as_administrator(self):
        """
        Instalarea nu are nevoie de drepturi. Pornită ca Administrator, fișierele ajung să
        aparțină altui cont decât cel care folosește bara, iar pasul cu HWiNFO își cere
        singur drepturile când e nevoie.
        """
        self.assertIn("net session", self.text)

    def test_the_options_it_advertises_are_real(self):
        """Opțiunile scrise în comentariu trebuie să existe în script."""
        setup = SETUP.read_text(encoding="utf-8")
        # blocul se termină la paranteza singură pe rândul ei: comentariile dinăuntru au și ele paranteze
        declared = re.search(r"^param\s*\(\s*$(.*?)^\)\s*$", setup, re.S | re.M)
        self.assertIsNotNone(declared, "nu găsesc blocul param din setup.ps1")
        known = set(re.findall(r"\[\w+\]\$(\w+)", declared.group(1)))
        self.assertIn("YasbPath", known, "extragerea opțiunilor nu mai funcționează")
        for option in re.findall(r"instalare\.bat\s+-(\w+)", self.text):
            self.assertIn(option, known, f"-{option} nu există în setup.ps1")


if __name__ == "__main__":
    unittest.main()
