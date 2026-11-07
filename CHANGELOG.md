# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Daemon reading the GSX 1000/1200 wheel from `/dev/hidraw0` and driving
  `wpctl set-volume` on a target sink.
- Burst-based tick detection: counts identical reports per run instead of
  relying on direction changes, so repeated same-direction detents are not
  swallowed.
- Runtime resolution of `GSX_SINK` from a PipeWire `node.name` to a numeric
  id, re-resolving when an id goes stale.
- systemd user unit with `Restart=on-failure` and basic sandboxing.
- udev rule granting the active session access via `uaccess` ACL.
- `install.sh`, `uninstall.sh`, `check.sh` helper scripts.
- 15 unit tests, including a replay of a real six-detent HID capture.

### Documented
- Troubleshooting for "wheel only turns volume down": `PCM,1` pinned at
  its maximum (74) stops the firmware from reporting volume-up; lower it to
  70 and run `alsactl store`.
- The wheel also emits standard `KEY_VOLUMEUP`/`KEY_VOLUMEDOWN` that
  desktops handle natively; running the daemon alongside double-steps.
- Clarified the two playback controls (`PCM,0` two-step, `PCM,1` real
  gain) and that neither profile binds the sink volume to `PCM,1` in
  practice.

### Known issues
- Wheel/GSX display and OS volume drift apart; nothing writes the OS volume
  back to the GSX. See README "Wheel and OS volume drift apart".
- Two consecutive same-direction detents with no gap are byte-identical to
  one long detent and are reported as a single tick. Only inter-report
  timing could distinguish them; see README "Known limitation".
