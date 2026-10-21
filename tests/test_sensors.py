"""Citirea senzorilor și a stărilor: RivaTuner, HWiNFO, git, rețea, descărcări, notificări."""

import struct
import unittest

import stubs

stubs.install()

from core.widgets.yasb.bar_notifications import shorten  # noqa: E402
from core.widgets.yasb.git_branch import folder_from_title, parse_status  # noqa: E402
from core.widgets.yasb.hwinfo_sensor import parse_shared_memory, pick_reading  # noqa: E402
from core.widgets.yasb.net_status import Adapter, format_speed, pick_connection  # noqa: E402
from core.widgets.yasb.progress_line import IDLE_MS, torrents_progress, tick_interval  # noqa: E402
from core.widgets.yasb.rtss_fps import parse_rtss  # noqa: E402

# ----------------------------------------------------------------- RivaTuner

RTSS_SIGNATURE = 0x52545353
APP_NAME_LEN = 260
ENTRY_SIZE = 4 + APP_NAME_LEN + 20


def rtss_buffer(apps, signature=RTSS_SIGNATURE, entry_size=ENTRY_SIZE):
    header = struct.pack("<8I", signature, 2, entry_size, 32, len(apps), 0, 0, 0)
    body = b""
    for pid, name, frames, t0, t1, frame_time_us in apps:
        raw = name.encode("latin-1")
        body += struct.pack("<I", pid)
        body += raw + b"\0" * (APP_NAME_LEN - len(raw))
        body += struct.pack("<5I", 0, t0, t1, frames, frame_time_us)
    return header + body


class TestRtss(unittest.TestCase):
    def test_reads_one_game(self):
        buf = rtss_buffer([(1234, r"C:\Games\eldenring.exe", 600, 0, 10000, 16667)])
        apps = parse_rtss(buf)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].pid, 1234)
        self.assertEqual(apps[0].name, "eldenring.exe")  # doar numele, fără cale
        self.assertAlmostEqual(apps[0].fps, 60.0, places=3)
        self.assertAlmostEqual(apps[0].frametime_ms, 16.667, places=3)

    def test_wrong_signature_is_refused(self):
        self.assertEqual(parse_rtss(rtss_buffer([], signature=0xDEAD)), [])

    def test_empty_slots_are_skipped(self):
        buf = rtss_buffer([(0, "", 0, 0, 0, 0), (7, "cs2.exe", 300, 0, 5000, 3333)])
        apps = parse_rtss(buf)
        self.assertEqual([a.name for a in apps], ["cs2.exe"])

    def test_no_time_elapsed_means_no_fps(self):
        apps = parse_rtss(rtss_buffer([(9, "game.exe", 100, 500, 500, 1000)]))
        self.assertEqual(apps[0].fps, 0.0)

    def test_a_truncated_buffer_does_not_crash(self):
        self.assertEqual(parse_rtss(b"\x00" * 10), [])

    def test_an_impossible_entry_size_is_refused(self):
        self.assertEqual(parse_rtss(rtss_buffer([], entry_size=8)), [])


# ----------------------------------------------------------------- HWiNFO

SENSOR_SIZE = 264
READING_SIZE = 316
HWINFO_SIGNATURE = 0x53695748


def _fixed(text, length):
    raw = text.encode("latin-1")
    return raw + b"\0" * (length - len(raw))


def hwinfo_buffer(sensors, readings, signature=HWINFO_SIGNATURE):
    s_off = 44
    r_off = s_off + SENSOR_SIZE * len(sensors)
    header = struct.pack(
        "<IIIqIIIIII", signature, 1, 0, 1000, s_off, SENSOR_SIZE, len(sensors), r_off, READING_SIZE, len(readings)
    )
    body = b""
    for name in sensors:
        body += b"\0" * 8 + _fixed(name, 128) + _fixed("", 128)
    for rtype, s_idx, r_id, label, unit, value in readings:
        body += struct.pack("<III", rtype, s_idx, r_id)
        body += _fixed(label, 128) + _fixed("", 128) + _fixed(unit, 16)
        body += struct.pack("<dddd", value, value - 5, value + 5, value)
    return header + body


class TestHwinfo(unittest.TestCase):
    def test_reads_the_cpu_temperature(self):
        buf = hwinfo_buffer(["CPU [#0]: AMD Ryzen"], [(1, 0, 10, "CPU (Tctl/Tdie)", "°C", 54.5)])
        readings = parse_shared_memory(buf)
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].label, "CPU (Tctl/Tdie)")
        self.assertEqual(readings[0].unit, "°C")
        self.assertAlmostEqual(readings[0].value, 54.5)
        self.assertEqual(readings[0].sensor, "CPU [#0]: AMD Ryzen")

    def test_wrong_signature_is_refused(self):
        self.assertEqual(parse_shared_memory(hwinfo_buffer([], [], signature=0)), [])

    def test_a_truncated_buffer_does_not_crash(self):
        self.assertEqual(parse_shared_memory(b"\x00" * 12), [])

    def test_exact_label_beats_a_partial_one(self):
        readings = parse_shared_memory(
            hwinfo_buffer(
                ["CPU"],
                [(1, 0, 1, "CPU Package", "°C", 70.0), (1, 0, 2, "CPU", "°C", 50.0)],
            )
        )
        picked = pick_reading(readings, ["cpu"], 1, "")
        self.assertEqual(picked.label, "CPU")

    def test_the_reading_type_filters(self):
        readings = parse_shared_memory(
            hwinfo_buffer(["CPU"], [(7, 0, 1, "CPU Total", "%", 12.0), (1, 0, 2, "CPU Total", "°C", 50.0)])
        )
        self.assertEqual(pick_reading(readings, ["cpu total"], 1, "").unit, "°C")
        self.assertEqual(pick_reading(readings, ["cpu total"], 7, "").unit, "%")

    def test_nothing_matching_returns_nothing(self):
        readings = parse_shared_memory(hwinfo_buffer(["CPU"], [(1, 0, 1, "CPU", "°C", 50.0)]))
        self.assertIsNone(pick_reading(readings, ["gpu hot spot"], 1, ""))


# ----------------------------------------------------------------- git

class TestGitTitle(unittest.TestCase):
    def test_plain_title(self):
        self.assertEqual(folder_from_title("auth.ts - myrepo - Visual Studio Code"), "myrepo")

    def test_unsaved_marker_is_dropped(self):
        self.assertEqual(folder_from_title("● auth.ts - myrepo - Visual Studio Code"), "myrepo")

    def test_wsl_suffix_is_dropped(self):
        self.assertEqual(folder_from_title("a.ts - myrepo [WSL: Ubuntu] - Visual Studio Code"), "myrepo")

    def test_workspace_suffix_is_dropped(self):
        self.assertEqual(folder_from_title("a.ts - myrepo (Workspace) - Visual Studio Code"), "myrepo")

    def test_cursor_is_recognised(self):
        self.assertEqual(folder_from_title("main.py - proiect - Cursor"), "proiect")

    def test_another_app_gives_nothing(self):
        self.assertIsNone(folder_from_title("Inbox - Outlook"))

    def test_editor_without_a_project_gives_nothing(self):
        self.assertIsNone(folder_from_title("Visual Studio Code"))


class TestGitStatus(unittest.TestCase):
    def test_branch_and_counts(self):
        out = "# branch.oid abc123\n# branch.head main\n# branch.ab +2 -1\n1 .M N...\n1 M. N...\n"
        st = parse_status(out)
        self.assertEqual(st.branch, "main")
        self.assertEqual((st.ahead, st.behind), (2, 1))
        self.assertEqual(st.changes, 2)

    def test_clean_repo(self):
        st = parse_status("# branch.oid abc\n# branch.head main\n# branch.ab +0 -0\n")
        self.assertEqual(st.changes, 0)
        self.assertEqual((st.ahead, st.behind), (0, 0))

    def test_detached_head_shows_the_short_commit(self):
        st = parse_status("# branch.oid abcdef1234567890\n# branch.head (detached)\n")
        self.assertEqual(st.branch, "abcdef1")

    def test_empty_output(self):
        self.assertEqual(parse_status("").branch, "")


# ----------------------------------------------------------------- rețea

def adapter(name="Ethernet", desc="Realtek Gaming 2.5GbE", if_type=6, up=True, gateway=True, speed=1_000_000_000):
    return Adapter(name=name, description=desc, if_type=if_type, up=up, gateway=gateway, speed_bps=speed)


class TestConnection(unittest.TestCase):
    def test_cable_wins_over_wifi(self):
        wifi = adapter(name="Wi-Fi", desc="Intel AX200", if_type=71)
        self.assertEqual(pick_connection([wifi, adapter()]).if_type, 6)

    def test_a_real_card_wins_over_a_virtual_one(self):
        virtual = adapter(name="vEthernet", desc="Hyper-V Virtual Ethernet Adapter")
        real = adapter()
        self.assertEqual(pick_connection([virtual, real]).description, real.description)

    def test_a_card_without_a_gateway_is_not_the_connection(self):
        self.assertIsNone(pick_connection([adapter(gateway=False)]))

    def test_a_card_that_is_down_is_not_the_connection(self):
        self.assertIsNone(pick_connection([adapter(up=False)]))

    def test_nothing_means_offline(self):
        self.assertIsNone(pick_connection([]))

    def test_speed_text(self):
        self.assertEqual(format_speed(1_000_000_000), "1 Gbps")
        self.assertEqual(format_speed(2_500_000_000), "2.5 Gbps")
        self.assertEqual(format_speed(100_000_000), "100 Mbps")
        self.assertEqual(format_speed(0), "")


# ----------------------------------------------------------------- descărcări

class TestTorrents(unittest.TestCase):
    def test_weighted_by_size(self):
        # un fișier de 900 MB la 0 % și unul de 100 MB la 100 % -> 10 %
        value = torrents_progress([{"size": 900, "progress": 0.0}, {"size": 100, "progress": 1.0}])
        self.assertAlmostEqual(value, 0.1, places=6)

    def test_nothing_downloading(self):
        self.assertIsNone(torrents_progress([]))

    def test_zero_sizes_are_not_a_division_by_zero(self):
        self.assertIsNone(torrents_progress([{"size": 0, "progress": 0.5}]))

    def test_missing_fields_do_not_crash(self):
        self.assertIsNone(torrents_progress([{}]))

    def test_result_stays_between_zero_and_one(self):
        value = torrents_progress([{"size": 10, "progress": 5.0}])
        self.assertEqual(value, 1.0)

    def test_the_line_does_not_keep_the_bar_awake(self):
        """
        Bugetul din plan: în repaus, niciun cronometru sub o secundă.

        Linia de progres bătea de patru ori pe secundă non-stop, și când nu era muzică, și când
        nu era focus, și când nu descărcai nimic. Pe laptop asta se vedea în baterie.
        """
        self.assertGreaterEqual(tick_interval(drawing=False), 1000)
        self.assertEqual(tick_interval(drawing=False), IDLE_MS)
        self.assertLess(tick_interval(drawing=True), tick_interval(drawing=False))


# ----------------------------------------------------------------- notificări

class TestShorten(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(shorten("Salut", 20), "Salut")

    def test_long_text_gets_an_ellipsis(self):
        out = shorten("a" * 50, 10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.endswith("…"))

    def test_whitespace_is_collapsed(self):
        self.assertEqual(shorten("a  \n b", 20), "a b")


if __name__ == "__main__":
    unittest.main()
