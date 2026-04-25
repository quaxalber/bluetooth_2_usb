#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Missing repository virtualenv Python: %s\n' "$PYTHON_BIN" >&2
  printf 'Run the installer or create the repo venv before capturing device data.\n' >&2
  exit 3
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

exec "$PYTHON_BIN" -m bluetooth_2_usb.capture_device "$@"
