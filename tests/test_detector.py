#!/usr/bin/python3
"""Unit tests for the HID tick detector, including a replay of real data.

Run:  python3 -m unittest discover -s tests -v
"""

import importlib.util
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "gsx_wheel", REPO / "gsx-wheel-volume.py")
gsx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gsx)


def report(direction: int) -> bytes:
    return bytes([0x02, direction, 0x02, 0x00])


UP, DOWN = gsx.DIR_UP, gsx.DIR_DOWN


class TestDirectionOf(unittest.TestCase):
    def test_up_and_down(self):
        self.assertEqual(gsx.direction_of(report(UP)), 1)
        self.assertEqual(gsx.direction_of(report(DOWN)), -1)

    def test_rejects_wrong_length(self):
        self.assertIsNone(gsx.direction_of(b"\x02\x01\x02"))
        self.assertIsNone(gsx.direction_of(report(UP) + b"\x00"))

    def test_rejects_unknown_report_id(self):
        self.assertIsNone(gsx.direction_of(bytes([0x03, UP, 0x02, 0x00])))

    def test_rejects_unknown_direction(self):
        self.assertIsNone(gsx.direction_of(bytes([0x02, 0x07, 0x02, 0x00])))


class TestTickDetector(unittest.TestCase):
    def test_one_burst_is_one_tick(self):
        d = gsx.TickDetector()
        ticks = d.feed(report(UP) * 6, now=1.0)
        self.assertEqual(ticks, [1])

    def test_short_burst_below_minimum_is_ignored(self):
        d = gsx.TickDetector()
        self.assertEqual(d.feed(report(UP) * 3, now=1.0), [])

    def test_alternating_bursts(self):
        d = gsx.TickDetector()
        ticks = d.feed(report(UP) * 6, now=1.0)
        ticks += d.feed(report(DOWN) * 7, now=1.1)
        self.assertEqual(ticks, [1, -1])

    def test_two_detents_same_direction_without_gap_merge_KNOWN_LIMITATION(self):
        """KNOWN LIMITATION, documented deliberately.

        Two consecutive detents of the same direction that arrive back to
        back are byte-identical to one long detent:

            detent(13 reports)        -> 01 x13
            detent(6) + detent(7)     -> 01 x13

        No amount of value inspection can separate them; only inter-report
        timing can. We accept one tick here rather than guessing, because a
        false split would turn one slow turn into two volume steps.

        In the real capture every detent was a separate run (5, 8, 6, 7, 7,
        11 reports), so this only affects very fast same-direction spins.
        """
        d = gsx.TickDetector()
        stream = report(UP) * 6 + report(UP) * 7
        ticks = d.feed(stream, now=1.0)
        self.assertEqual(ticks, [1])

    def test_same_direction_after_idle_resets(self):
        d = gsx.TickDetector()
        self.assertEqual(d.feed(report(UP) * 6, now=1.0), [1])
        # Idle gap well beyond the timeout.
        self.assertEqual(d.feed(report(UP) * 6, now=1.5), [1])

    def test_short_gap_does_not_reset(self):
        d = gsx.TickDetector()
        self.assertEqual(d.feed(report(UP) * 6, now=1.0), [1])
        # Within the idle timeout the run continues, no second tick.
        self.assertEqual(d.feed(report(UP) * 2, now=1.01), [])

    def test_long_burst_emits_only_once(self):
        d = gsx.TickDetector()
        ticks = d.feed(report(UP) * 20, now=1.0)
        self.assertEqual(ticks, [1])

    def test_chunk_boundary_splits_burst(self):
        # The kernel may split a burst across reads.
        d = gsx.TickDetector()
        self.assertEqual(d.feed(report(UP) * 2, now=1.0), [])
        self.assertEqual(d.feed(report(UP) * 2, now=1.001), [1])

    def test_unaligned_trailing_bytes_are_dropped(self):
        d = gsx.TickDetector()
        # 6 full reports then 2 stray bytes.
        self.assertEqual(d.feed(report(UP) * 6 + b"\x02\x01", now=1.0), [1])


class TestReplayRealCapture(unittest.TestCase):
    """Replay the exact hidraw dump captured from a real GSX 1000."""

    CAPTURE = bytes.fromhex("""
        02 01 02 00 02 01 02 00 02 01 02 00 02 01 02 00
        02 01 02 00 02 02 02 00 02 02 02 00 02 02 02 00
        02 02 02 00 02 02 02 00 02 02 02 00 02 02 02 00
        02 02 02 00 02 01 02 00 02 01 02 00 02 01 02 00
        02 01 02 00 02 01 02 00 02 01 02 00 02 02 02 00
        02 02 02 00 02 02 02 00 02 02 02 00 02 02 02 00
        02 02 02 00 02 02 02 00 02 01 02 00 02 01 02 00
        02 01 02 00 02 01 02 00 02 01 02 00 02 01 02 00
        02 01 02 00 02 02 02 00 02 02 02 00 02 02 02 00
        02 02 02 00 02 02 02 00 02 02 02 00 02 02 02 00
        02 02 02 00 02 02 02 00 02 02 02 00 02 02
    """)

    def test_replay_produces_alternating_six_ticks(self):
        d = gsx.TickDetector()
        ticks = d.feed(self.CAPTURE, now=1.0)
        # Six detents, alternating: up down up down up down.
        self.assertEqual(ticks, [1, -1, 1, -1, 1, -1])

    def test_replay_independent_of_read_chunking(self):
        d = gsx.TickDetector()
        ticks = []
        data = self.CAPTURE
        # Simulate awkward 4-report-aligned read sizes.
        sizes = [13, 7, 21, 5, 9, 17, 3, 24]
        pos, i = 0, 0
        while pos < len(data):
            n = sizes[i % len(sizes)] * 4
            i += 1
            ticks += d.feed(data[pos:pos + n], now=1.0 + i * 0.001)
            pos += n
        self.assertEqual(ticks, [1, -1, 1, -1, 1, -1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
