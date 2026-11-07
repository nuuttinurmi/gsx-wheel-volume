# gsx-wheel-volume

Use the physical **volume wheel on the Sennheiser GSX 1000 / 1200** as the
PipeWire volume control on Linux, complete with the desktop volume OSD.

The GSX's firmware adjusts its own internal gain when the wheel turns. It
*also* reports each turn to the host over HID interface 05, which the
kernel exposes as a keyboard (`KEY_VOLUMEUP` / `KEY_VOLUMEDOWN`) and as
raw `/dev/hidraw0`. This daemon reads the raw node, translates each detent
into a `wpctl set-volume` call on the target sink, and leaves the desktop
slider as the single source of truth.

```
wheel -> /dev/hidraw0 -> gsx-wheel-volume.py -> wpctl set-volume -> PipeWire -> OSD
```

> **Before installing:** most desktops (KDE Plasma, GNOME) already act on
> the `KEY_VOLUMEUP`/`KEY_VOLUMEDOWN` events with their own OSD. With the
> daemon running too, each turn moves the volume twice. Check what your
> desktop does on its own first (see [Wheel and OS volume drift
> apart](#wheel-and-os-volume-drift-apart)).

## Why not just let the hardware wheel do it?

Tested on Fedora 44 / PipeWire 1.6.11 / KDE Plasma with a GSX 1000
(1395:00a0):

- The GSX has two playback volume controls. `PCM,0` has a two-step range
  (−0.1 dB … 0 dB; the kernel warns "Unlikely small volume range"). `PCM,1`
  (0–74, about 1 dB per step) is the GSX's real gain stage.
- Under the `2.0 HD` profile, PipeWire's sink binds `PCM,0`, so the OS
  slider is effectively software volume and never reaches `PCM,1`.
- The stock `sennheiser-gsx.conf` profile set lists `PCM,1` for the 7.1
  path, but in testing `PCM,1` did not follow the sink volume under 7.1
  either.
- Result: the OS slider and the GSX's internal gain are two independent
  gain stages.

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

### Turning right does nothing, turning left still works

The display/LED ring moves both ways, but only `KEY_VOLUMEDOWN` reaches the
host. Confirm with:

```bash
sudo timeout 20 libinput debug-events --show-keycodes --device /dev/input/event2
```

Cause: **`PCM,1` is at its maximum (74).** The GSX firmware stops
reporting "up" to the host when its internal gain has no headroom, but
keeps reporting "down". Windows keeps that control in sync with its own
volume slider, so it never sits at the top there. On Linux nothing drives
it (see above), so once it is at maximum it stays there.

Fix: give it a few steps of headroom and save the mixer state:

```bash
amixer -c0 sget PCM,1          # 74 = pinned at maximum
amixer -c0 sset PCM,1 70       # 73 was NOT enough on the test unit; 70 works
sudo alsactl store             # persist across reboots
```

`70` costs 4 dB at full volume. Replace `-c0` with your GSX card number
from `cat /proc/asound/cards`.

Note: `amixer` shows the driver's cached value. Turning the wheel did not
change what `amixer` reports, so it cannot tell you where the firmware's
internal gain currently is.

### Wheel and OS volume drift apart

On Windows the wheel, the GSX display and the OS volume stay in step. On
Linux they drift, because the OS slider and the GSX's internal gain are
separate (see [Why not just let the hardware wheel
do it?](#why-not-just-let-the-hardware-wheel-do-it)):

- The wheel changes the GSX's internal gain in its own steps and sends key
  events. The desktop then moves the sink by its own step size (KDE:
  `VolumeStep` in `~/.config/plasmaparc`).
- Nothing writes the OS volume back to the GSX, so the display does not
  follow the OS slider.

Not solved yet. The likely fix is to make the sink's hardware volume drive
`PCM,1` (as Windows does), but that has not been verified.

### Service runs but the wheel does nothing

```bash
ls -l /dev/hidraw0       # crw-rw----+ root input
id -nG                   # is your user in group input / does the ACL apply?
```

Re-apply the udev rule:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change
```

### "cannot find sink"

The `GSX_SINK` name does not match any node:

```bash
wpctl status | grep GSX
pw-dump | grep -o '"node.name".*GSX[^"]*'
```

### Volume moves two steps per detent

First check that the desktop isn't also handling the wheel's volume keys
(see the note at the top). Otherwise, lower `GSX_BURST_MIN` to 3; the
firmware may emit shorter bursts on your unit.

### Volume not moving in a game

Some apps set their own per-stream
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
