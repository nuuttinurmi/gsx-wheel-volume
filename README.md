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

> **Try the [hardware volume override](#recommended-hardware-volume-override)
> first.** On KDE Plasma it made the wheel, the GSX display and the OS
> slider work together without this daemon. Most desktops (KDE Plasma,
> GNOME) already act on the `KEY_VOLUMEUP`/`KEY_VOLUMEDOWN` events with
> their own OSD; running the daemon as well moves the volume twice per turn.

## How the GSX volume works

Tested on Fedora 44 / PipeWire 1.6.11 / WirePlumber 0.5.19 / KDE Plasma
with a GSX 1000 (1395:00a0):

- The GSX has two playback volume controls. `PCM,0` has a two-step range
  (−0.1 dB … 0 dB; the kernel warns "Unlikely small volume range"). `PCM,1`
  (0–74, −74 dB … 0 dB, 1 dB per step) is the GSX's real gain stage, and
  the one its LED ring/display shows.
- Turning the wheel changes the GSX's gain inside the firmware and sends
  `KEY_VOLUMEUP` / `KEY_VOLUMEDOWN`. The firmware does **not** report its
  new gain back over USB, so `amixer` keeps showing the last value the
  host wrote.
- The firmware stops sending `KEY_VOLUMEUP` when its gain is at maximum,
  but keeps sending `KEY_VOLUMEDOWN`.
- **On Windows** the system volume *is* `PCM,1`: the OS writes its volume
  to the device, so the wheel, the display and the slider stay in step,
  and the gain only sits at maximum when the OS volume is at 100%.

### Why it breaks on stock PipeWire

The stock `sennheiser-gsx.conf` profile set marks both GSX profiles
`skip-probe = yes`. ACP only builds mixer paths while probing, so with
`skip-probe` **no output gets a mixer path** (`spa-acp-tool -c <card>
list-verbose` shows `ports: (0)` for every GSX output). The 7.1 path even
lists `[Element PCM,1]`, but it is never loaded.

Consequences:

- The OS slider never reaches `PCM,1`. It and the GSX's gain are two
  independent gain stages, so the display does not follow the slider.
- Nothing ever lowers `PCM,1`. Once it reaches maximum it stays there, and
  the wheel only turns volume **down** (see
  [Troubleshooting](#turning-right-does-nothing-turning-left-still-works)).

## Recommended: hardware volume override

`alsa-card-profile/` contains a per-user override that does what Windows
does: the sink's hardware volume drives `PCM,1`.

- `profile-sets/sennheiser-gsx.conf`: the stock profile set with
  `skip-probe` removed, and the `2.0 HD` mapping given an output path.
- `paths/sennheiser-gsx-pcm1.conf`: binds `PCM,1` as volume and mute
  (same element settings as the stock 7.1 path).

ACP looks in `$XDG_CONFIG_HOME/alsa-card-profile/mixer` before
`/usr/share`, so this affects only your user:

```bash
mkdir -p ~/.config/alsa-card-profile/mixer
cp -r alsa-card-profile/profile-sets alsa-card-profile/paths ~/.config/alsa-card-profile/mixer/
systemctl --user restart wireplumber     # audio drops out briefly
```

Verify:

```bash
pactl list sinks | grep -E 'Name:|Flags:|Active Port:'
# 2.0 HD sink: Flags include HW_VOLUME_CTRL, Active Port: sennheiser-gsx-pcm1
for v in 1.00 0.60; do wpctl set-volume @DEFAULT_AUDIO_SINK@ $v; sleep .3; amixer -c0 sget PCM,1 | grep 'Front Left'; done
# 1.00 -> 74 [0.00dB], 0.60 -> 61 [-13.00dB]
```

Measured mapping (2.0 HD): 100% → 74 (0 dB), 80% → 69, 60% → 61, 40% → 51.

Result on the test machine: the wheel works in both directions, the GSX
display follows the KDE slider, and the slider follows the wheel. Only the
`2.0 HD` profile was tested; 7.1 should now bind `PCM,1` through its stock
path, but that is unverified.

Remove:

```bash
rm ~/.config/alsa-card-profile/mixer/profile-sets/sennheiser-gsx.conf \
   ~/.config/alsa-card-profile/mixer/paths/sennheiser-gsx-pcm1.conf
systemctl --user restart wireplumber
```

The real fix belongs upstream in PipeWire's `sennheiser-gsx.conf` (drop
`skip-probe`, give `stereo-output` a `PCM,1` path); not reported yet.

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

Cause: **the GSX's gain is at its maximum (`PCM,1` = 74).** The firmware
stops reporting "up" when its gain has no headroom, but keeps reporting
"down". On stock PipeWire nothing ever lowers `PCM,1` (see [Why it breaks
on stock PipeWire](#why-it-breaks-on-stock-pipewire)).

Fix: install the [hardware volume
override](#recommended-hardware-volume-override). The OS volume then sets
`PCM,1`, so the gain is only at maximum when the OS volume is at 100%.

Fallback without the override: give the gain some headroom by hand and
save the mixer state:

```bash
amixer -c0 sget PCM,1          # 74 = pinned at maximum
amixer -c0 sset PCM,1 70       # 73 was NOT enough on the test unit; 70 works
sudo alsactl store             # persist across reboots
```

This loses 4 dB at full volume, and turning the wheel up can pin it at the
maximum again. Replace `-c0` with your GSX card number from
`cat /proc/asound/cards`.

### Wheel and OS volume drift apart

On stock PipeWire the OS slider and the GSX's gain are separate (see [How
the GSX volume works](#how-the-gsx-volume-works)), so the display does
not follow the slider and the two drift. The [hardware volume
override](#recommended-hardware-volume-override) fixes this: with it the
GSX display follows the KDE slider.

### KDE slider occasionally stops moving while the sound still changes (open)

With the override installed, turning the wheel sometimes makes the sound
louder while KDE's slider/OSD stays still. Not diagnosed yet. Working
theory: the firmware changes its gain on every detent but some
`KEY_VOLUMEUP` events do not reach (or are not acted on by) the desktop,
and since the GSX never reports its gain back, the host cannot notice. To
check, log `libinput debug-events --device /dev/input/event2` side by side
with `wpctl get-volume @DEFAULT_AUDIO_SINK@` while reproducing it.

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
(see the note at the top of this README). Otherwise, lower `GSX_BURST_MIN` to 3; the
firmware may emit shorter bursts on your unit.

### Volume not moving in a game

Some apps set their own per-stream
volume; this daemon moves the *sink*, not individual streams.

## Files

```
gsx-wheel-volume.py              the daemon
systemd/gsx-wheel-volume.service user unit
udev/70-sennheiser-gsx-wheel.rules
alsa-card-profile/profile-sets/sennheiser-gsx.conf   PCM,1 override (profile set)
alsa-card-profile/paths/sennheiser-gsx-pcm1.conf     PCM,1 override (2.0 HD path)
scripts/install.sh               install + enable
scripts/uninstall.sh             remove
tests/test_detector.py           unit tests
```

## Licence

MIT. See `LICENSE`.

Not affiliated with Sennheiser / DSEA A/S.
