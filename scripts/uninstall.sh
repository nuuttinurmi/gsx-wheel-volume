#!/usr/bin/env bash
# Remove the GSX wheel volume bridge for the current user.
set -euo pipefail

BIN="${HOME}/.local/bin/gsx-wheel-volume.py"
UNIT="${HOME}/.config/systemd/user/gsx-wheel-volume.service"
UDEV_DST="/etc/udev/rules.d/70-sennheiser-gsx-wheel.rules"

echo "==> stopping and disabling service"
systemctl --user disable --now gsx-wheel-volume.service 2>/dev/null || true

echo "==> removing files"
rm -f "$UNIT" "$BIN"
systemctl --user daemon-reload

echo "==> removing udev rule (sudo required)"
sudo rm -f "$UDEV_DST"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change

echo "Done."
