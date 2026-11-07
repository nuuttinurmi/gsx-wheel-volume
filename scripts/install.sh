#!/usr/bin/env bash
# Install the GSX wheel volume bridge for the current user.
#
#   ./scripts/install.sh          # install and start
#   ./scripts/install.sh --no-enable   # install but do not start
#
# Needs sudo only for the udev rule.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
UNIT_DIR="${HOME}/.config/systemd/user"
UDEV_DST="/etc/udev/rules.d/70-sennheiser-gsx-wheel.rules"
ENABLE=1

for arg in "$@"; do
    case "$arg" in
        --no-enable) ENABLE=0 ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

echo "==> installing daemon to ${BIN_DIR}"
mkdir -p "$BIN_DIR"
install -m 0755 "${REPO_DIR}/gsx-wheel-volume.py" "${BIN_DIR}/gsx-wheel-volume.py"

echo "==> installing user unit to ${UNIT_DIR}"
mkdir -p "$UNIT_DIR"
install -m 0644 "${REPO_DIR}/systemd/gsx-wheel-volume.service" \
    "${UNIT_DIR}/gsx-wheel-volume.service"

echo "==> installing udev rule (sudo required)"
sudo install -m 0644 "${REPO_DIR}/udev/70-sennheiser-gsx-wheel.rules" "$UDEV_DST"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change

echo "==> reloading systemd --user"
systemctl --user daemon-reload

if [[ $ENABLE -eq 1 ]]; then
    echo "==> enabling and starting service"
    systemctl --user enable --now gsx-wheel-volume.service
else
    echo "==> installed, not started (--no-enable)"
fi

echo
echo "Done. Check status with:"
echo "  systemctl --user status gsx-wheel-volume.service"
echo "  ls -l /dev/hidraw0   # should now be accessible to you"
