#!/usr/bin/python3
"""
Sennheiser GSX 1000/1200 rotary-wheel -> PipeWire volume bridge.

The GSX 1000 exposes its volume wheel as a raw HID device (1395:00a0,
interface 05) emitting 4-byte relative reports:  02 <dir> 02 00
  dir 0x01 = one notch up, dir 0x02 = one notch down.

A single physical detent emits a burst of 5-10 *identical* consecutive
reports. Two detents in the same direction arrive as two contiguous
bursts of the same byte (e.g. 6x 01 then 7x 01). We therefore cannot
use "direction changed" as the tick boundary.

Instead we track how many identical reports we have consumed in the
current run. Empirically one detent emits >= ~4 reports, so we count a
tick once a run reaches BURST_MIN reports, then wait for the byte value
to change (or a short idle gap) before starting a new run.

Volume is applied with `wpctl set-volume`, which drives the PipeWire
node volume. That is deliberate: on this card the ALSA 'PCM,1' hardware
fader is not bound to the node mixer in the 2.0 HD profile, so using
the node keeps a single source of truth and makes the desktop OSD track
the wheel.
"""

import json
import os
import subprocess
import sys
import time

HIDRAW = os.environ.get("GSX_HIDRAW", "/dev/hidraw0")

# Target sink. Prefer the stable node.name over a numeric id, because
# PipeWire node ids change across restarts and re-plugs. wpctl itself
# only accepts numeric ids, so the name is resolved at runtime.
SINK = os.environ.get(
    "GSX_SINK",
    "alsa_output.usb-Sennheiser_GSX_1000_Main_Audio_5698800499047002-00.stereo-output",
)

STEP = os.environ.get("GSX_STEP", "1%")      # volume step per detent

REPORT_LEN = 4
DIR_UP = 0x01
DIR_DOWN = 0x02

# Reports per physical detent is 5-10; require a minimum so a single
# stray byte does not move volume.
BURST_MIN = int(os.environ.get("GSX_BURST_MIN", "4"))

# Gap that ends a run and allows re-detection of the same direction.
IDLE_TIMEOUT = float(os.environ.get("GSX_IDLE_TIMEOUT", "0.06"))  # seconds

# Seconds to sleep when the hidraw node has nothing to read.
POLL_INTERVAL = 0.005

_resolved_id = None


def log(msg: str) -> None:
    print(f"gsx-wheel: {msg}", file=sys.stderr, flush=True)


def resolve_sink_id() -> str | None:
    """Return the numeric node id for SINK, or None if not found."""
    if SINK.isdigit():
        return SINK
    try:
        out = subprocess.run(
            ["pw-dump"], check=False, timeout=3,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout
        for node in json.loads(out):
            if node.get("type") != "PipeWire:Interface:Node":
                continue
            props = node.get("info", {}).get("props", {})
            if props.get("node.name") == SINK:
                return str(node["id"])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log(f"resolve failed: {exc}")
    return None


def set_volume(direction: int) -> None:
    global _resolved_id
    sign = "+" if direction > 0 else "-"

    if _resolved_id is None:
        _resolved_id = resolve_sink_id()
    if _resolved_id is None:
        log(f"cannot find sink {SINK}")
        return

    try:
        subprocess.run(
            ["wpctl", "set-volume", _resolved_id, f"{STEP}{sign}"],
            check=False, timeout=2,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # A failed lookup usually means the cached id went stale; clear
        # it so the next tick re-resolves.
        alive = subprocess.run(
            ["wpctl", "get-volume", _resolved_id],
            check=False, timeout=2,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        if not alive:
            _resolved_id = None
    except (OSError, subprocess.SubprocessError) as exc:
        _resolved_id = None
        log(f"set-volume failed: {exc}")


def direction_of(report: bytes) -> int | None:
    """Map one 4-byte HID report to +1 (up), -1 (down) or None."""
    if len(report) != REPORT_LEN or report[0] != 0x02:
        return None
    if report[1] == DIR_UP:
        return 1
    if report[1] == DIR_DOWN:
        return -1
    return None


class TickDetector:
    """Turn the burst-oriented HID stream into one event per detent.

    Kept as a class so it can be unit-tested without hardware.
    feed() takes one byte of the report stream at a time, or a chunk.
    """

    def __init__(self, burst_min: int = BURST_MIN,
                 idle_timeout: float = IDLE_TIMEOUT) -> None:
        self.burst_min = burst_min
        self.idle_timeout = idle_timeout
        self.run_dir: int | None = None
        self.run_count = 0
        self.emitted = False
        self.last_event = 0.0

    def _expire(self, now: float) -> None:
        if self.run_dir is not None and now - self.last_event > self.idle_timeout:
            self.run_dir = None
            self.run_count = 0
            self.emitted = False

    def feed(self, chunk: bytes, now: float) -> list[int]:
        """Return a list of ticks (+1/-1) produced by this chunk."""
        self._expire(now)
        ticks = []
        for i in range(0, len(chunk) - REPORT_LEN + 1, REPORT_LEN):
            d = direction_of(chunk[i:i + REPORT_LEN])
            if d is None:
                continue
            self.last_event = now
            if d != self.run_dir:
                self.run_dir = d
                self.run_count = 1
                self.emitted = False
            else:
                self.run_count += 1

            if not self.emitted and self.run_count >= self.burst_min:
                self.emitted = True
                ticks.append(d)
        return ticks


def main() -> int:
    try:
        fd = os.open(HIDRAW, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        log(f"cannot open {HIDRAW}: {exc}")
        return 1

    detector = TickDetector()
    log(f"listening on {HIDRAW}, sink {SINK}, step {STEP}")

    try:
        while True:
            try:
                data = os.read(fd, 64)
            except BlockingIOError:
                data = b""
            except OSError as exc:
                log(f"read error: {exc}")
                time.sleep(0.5)
                continue

            if not data:
                time.sleep(POLL_INTERVAL)
                continue

            for direction in detector.feed(data, time.monotonic()):
                set_volume(direction)
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
