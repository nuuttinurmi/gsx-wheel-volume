# gsx-wheel-volume

Use the physical **volume wheel on the Sennheiser GSX 1000 / 1200** as the
PipeWire volume control on Linux, complete with the desktop volume OSD.

The GSX exposes its wheel as a raw HID device. The DAC's firmware adjusts
its own internal gain, which userspace (and therefore the desktop volume
slider) never sees. This daemon reads the wheel, translates each detent
into a `wpctl set-volume` call on the target sink, and leaves the desktop
slider as the single source of truth.

```
wheel -> /dev/hidraw0 -> gsx-wheel-volume.py -> wpctl set-volume -> PipeWire -> OSD
```

## Why not just let the hardware wheel do it?

Tested on Fedora 44 / PipeWire 1.6.11 with a GSX 1000 (1395:00a0):

- The ALSA fader (`PCM,1`) the wheel drives is **not bound to the PipeWire
  node mixer** under the `2.0 HD` card profile, so the software slider and
  the wheel are two independent gain stages.
- The result is double attenuation, no OSD, and a slider that does not
  reflect what you actually hear.

Reading the wheel directly removes the ambiguity.

## Install

```bash
git clone https://github.com/nuuttinurmi/gsx-wheel-volume.git ~/projects/gsx-wheel-volume
cd ~/projects/gsx-wheel-volume
./scripts/install.sh
```

This will:

1. copy the daemon to `~/.local/bin/gsx-wheel-volume.py`
2. install `gsx-wheel-volume.service` as a **user** unit
3. install a udev rule granting your user access to `/dev/hidraw0` (sudo)
4. enable and start the service

Install without starting it:

```bash
./scripts/install.sh --no-enable
```

Uninstall:

```bash
./scripts/uninstall.sh
```

Nothing is restarted or reloaded: installing cannot interrupt audio that
is already playing.

## Requirements

| Component | Notes |
|---|---|
| Python 3.9+ | stdlib only, no pip packages |
| PipeWire + WirePlumber | provides `wpctl` and `pw-dump` |
| Sennheiser GSX 1000 / 1200 | USB `1395:00a0`, HID interface 05 |

## Configuration

Environment variables, set in the unit or your shell:

| Variable | Default | Meaning |
|---|---|---|
| `GSX_HIDRAW` | `/dev/hidraw0` | hidraw node of the wheel |
| `GSX_SINK` | `..._00.stereo-output` | sink `node.name` or numeric id |
| `GSX_STEP` | `1%` | volume change per detent |
| `GSX_BURST_MIN` | `4` | reports required before one detent counts |
| `GSX_IDLE_TIMEOUT` | `0.06` | seconds of silence that ends a burst |

`GSX_SINK` accepts a Node **name** (resolved at runtime, survives reboots)
or a numeric id. Using the name is strongly preferred — PipeWire node ids
change between sessions.

If you switch the card back to the 7.1 profile, update the unit:

```ini
Environment=GSX_SINK=alsa_output.usb-Sennheiser_GSX_1000_Main_Audio_..._00.analog-output-surround71
```

## The HID protocol

A 4-byte relative report per event:

```
02 01 02 00    0x01 = one notch up
02 02 02 00    0x02 = one notch down
```

One physical detent emits a **burst of 5–11 identical reports**. Two
detents in the same direction arrive as two adjacent bursts of the same
byte. Therefore "the direction changed" is not a usable tick boundary —
the detector counts reports in a run instead.

Real capture, six detents:

```
UP x5, DOWN x8, UP x6, DOWN x7, UP x7, DOWN x11   -> 6 ticks
```

### Known limitation

Two detents of the *same* direction with no gap between them are
byte-identical to a single long detent:

```
one detent of 13 reports   ->  01 x13
detent(6) + detent(7)      ->  01 x13
```

Only inter-report timing distinguishes these. The detector deliberately
reports one tick rather than guessing, so a very fast same-direction spin
may under-count. Changing direction, or pausing between clicks, is always
exact.

## Verify it works

```bash
systemctl --user status gsx-wheel-volume.service
systemctl --user logs -f gsx-wheel-volume.service   # if you add logging
ls -l /dev/hidraw0                                  # should be accessible
```

Turn the wheel: the desktop volume OSD should appear and the slider
should follow.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

15 tests cover report parsing, burst segmentation, chunk-boundary splits,
idle resets, and a replay of a real six-detent capture.

## Troubleshooting

**Service runs but the wheel does nothing**

```bash
ls -l /dev/hidraw0       # crw-rw----+ root input
id -nG                   # is your user in group input / does the ACL apply?
```

Re-apply the udev rule:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change
```

**"cannot find sink"** — the `GSX_SINK` name does not match any node:

```bash
wpctl status | grep GSX
pw-dump | grep -o '"node.name".*GSX[^"]*'
```

**Volume moves two steps per detent** — lower `GSX_BURST_MIN` to 3, or the
firmware emits shorter bursts on your unit.

**Volume not moving in a game** — some apps set their own per-stream
volume; this daemon moves the *sink*, not individual streams.

## Files

```
gsx-wheel-volume.py              the daemon
systemd/gsx-wheel-volume.service user unit
udev/70-sennheiser-gsx-wheel.rules
scripts/install.sh               install + enable
scripts/uninstall.sh             remove
tests/test_detector.py           unit tests
```

## Licence

MIT. See `LICENSE`.

Not affiliated with Sennheiser / DSEA A/S.
