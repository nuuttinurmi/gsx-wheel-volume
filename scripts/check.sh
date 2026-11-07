#!/usr/bin/env bash
# Quick self-check before committing.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "==> python syntax"
python3 -m py_compile gsx-wheel-volume.py

echo "==> shell syntax"
bash -n scripts/install.sh scripts/uninstall.sh

echo "==> unit tests"
python3 -m unittest discover -s tests

echo "==> all good"
