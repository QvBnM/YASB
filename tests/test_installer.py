"""
Fișierul de instalare pentru dublu-click.

Un .bat se citește cu pagina de cod a consolei, nu cu UTF-8, iar cmd.exe se poartă ciudat cu
sfârșituri de linie Unix. Lucrurile astea nu se văd până nu dai dublu-click pe calculatorul
unde contează, deci le verificăm aici.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mint_check import patch_problems  # noqa: E402

PATCH_TOOL = REPO / "tools" / "yasb_patch.py"


def put_patches(root: Path) -> int:
    """Pune peticele exact cum o face setup.ps1, si intoarce codul de ieșire pe care il vede el."""
    done = subprocess.run([sys.executable, str(PATCH_TOOL), str(root)], capture_output=True, text=True)
    return done.returncode
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


class TestHWiNFOIsLeftAlone(unittest.TestCase):
    """
    Dacă HWiNFO e deja instalat, setat și pornit, instalarea nu-l mai atinge.

    Până acum, la fiecare rulare: cerea Administrator, oprea HWiNFO, îi rescria fișierul de
    setări, refăcea sarcina programată și îl pornea din nou — chiar când totul era deja bine.
    """

    HW = REPO / "tools" / "hwinfo_setup.ps1"

    def setUp(self):
        self.hw = self.HW.read_text(encoding="utf-8")
        self.setup = SETUP.read_text(encoding="utf-8")

    def test_it_can_just_look(self):
        self.assertIn("[switch]$CheckOnly", self.hw)

    def test_looking_does_not_need_administrator(self):
        """Altfel verificarea ar cere chiar acordul pe care vrem să-l evităm."""
        self.assertIn("if (-not $CheckOnly -and -not $admin)", self.hw)

    def test_the_installer_looks_before_it_asks(self):
        check = self.setup.index("-CheckOnly")
        elevate = self.setup.index("Start-Process powershell -Verb RunAs")
        self.assertLess(check, elevate, "cere Administrator înainte să se uite dacă e cazul")

    def test_nothing_is_touched_when_all_is_well(self):
        self.assertIn("nu ating nimic", self.hw)
        self.assertIn("nu-l ating si nu cer Administrator", self.setup)

    def test_hwinfo_is_only_stopped_when_settings_must_change(self):
        """Oprirea programului e scumpă: se face doar dacă chiar avem ce scrie în fișier."""
        guard = self.hw.index("if ($needIni) {")
        stop = self.hw.index("Stop-Process -Force -ErrorAction SilentlyContinue")
        self.assertLess(guard, stop, "oprește HWiNFO înainte să știe dacă e nevoie")

    def test_you_can_still_force_it(self):
        self.assertIn("[switch]$Force", self.hw)
        self.assertIn("ForceHWiNFO", self.setup)

    def test_the_wanted_settings_are_written_down_once(self):
        """Verificarea și repararea trebuie să se uite la aceeași listă, nu la două copii."""
        both = self.hw + self.setup
        self.assertEqual(both.count('"SensorsSM"'), 1)


class TestThePatchesAreNotOptional(unittest.TestCase):
    """
    Peticele puse în sursa YASB sunt verificate, nu doar sperate.

    setup.ps1 dă `git checkout --` peste main.py și bar.py la fiecare instalare, ca să poată
    schimba versiunea, apoi le repune. Dacă repunerea nu reușește — YASB și-a mutat un rând —
    yasb_patch scria doar un rând galben și instalarea mergea înainte încă două minute, ca să
    pornească la final o bară care nu apare: fără QT_API=pyqt6, qasync ia PyQt5 dacă alt
    program l-a instalat, și nimic nu mai pornește.
    """

    def fake_yasb(self, with_qasync=True, with_anchor=True):
        root = Path(tempfile.mkdtemp(prefix="fakeyasb-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "src" / "core").mkdir(parents=True)
        main = "import sys\nimport qasync\n" if with_qasync else "import sys\n"
        (root / "src" / "main.py").write_text(main, encoding="utf-8")
        body = "        self.bar_frame.setLayout(bar_layout)\n" if with_anchor else "        pass\n"
        (root / "src" / "core" / "bar.py").write_text(f"class Bar:\n    def build(self):\n{body}", encoding="utf-8")
        return root

    def test_a_patched_yasb_passes(self):
        root = self.fake_yasb()
        self.assertEqual(put_patches(root), 0)
        problems, notes = patch_problems(root / "src")
        self.assertEqual(problems, [])
        self.assertEqual(len(notes), 2, notes)

    def test_putting_them_twice_changes_nothing(self):
        root = self.fake_yasb()
        put_patches(root)
        before = (root / "src" / "main.py").read_text(encoding="utf-8")
        self.assertEqual(put_patches(root), 0)
        self.assertEqual((root / "src" / "main.py").read_text(encoding="utf-8"), before)

    def test_the_qt_patch_missing_stops_the_install(self):
        root = self.fake_yasb(with_qasync=False)
        self.assertEqual(put_patches(root), 1, "codul de ieșire trebuie să spună că a eșuat")
        problems, _ = patch_problems(root / "src")
        self.assertEqual(len(problems), 1)
        self.assertIn("main.py", problems[0])

    def test_a_reverted_patch_is_caught_too(self):
        """Cazul real: peticul s-a pus odată, apoi `git checkout --` l-a dat jos."""
        root = self.fake_yasb()
        put_patches(root)
        (root / "src" / "main.py").write_text("import sys\nimport qasync\n", encoding="utf-8")
        problems, _ = patch_problems(root / "src")
        self.assertEqual(len(problems), 1)

    def test_the_clock_patch_only_warns(self):
        """Ceasul necentrat e urât, nu stricat: nu oprește instalarea."""
        root = self.fake_yasb(with_anchor=False)
        self.assertEqual(put_patches(root), 0)
        problems, notes = patch_problems(root / "src")
        self.assertEqual(problems, [])
        self.assertTrue(any("bar.py" in n for n in notes), notes)

    def test_the_installer_checks_that_exit_code(self):
        # assertTrue, nu assertIn: altfel mesajul de eșec tipărește tot setup.ps1 în consolă
        setup = SETUP.read_text(encoding="utf-8", errors="replace")
        self.assertTrue("$patchExit" in setup, "setup.ps1 nu se uită la codul de ieșire al peticelor")
        self.assertTrue(
            re.search(r"\$patchExit -ne 0.*throw", setup) is not None,
            "setup.ps1 citește codul de ieșire al peticelor, dar nu oprește instalarea la el",
        )

    def test_the_doctor_checks_the_patches_too(self):
        doctor = (REPO / "tools" / "mint_doctor.py").read_text(encoding="utf-8")
        self.assertTrue("def check_patches" in doctor, "doctorul nu are verificarea peticelor")
        self.assertTrue("check_patches(yasb)," in doctor, "verificarea peticelor există, dar nu e pusă în listă")
