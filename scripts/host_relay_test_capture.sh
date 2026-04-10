#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN=""

usage() {
  cat <<EOF
Usage: sudo ./scripts/host_relay_test_capture.sh [test_harness capture options]

Capture relay events from the host-side gadget nodes using the repository Python
environment.
Example:
  sudo ./scripts/host_relay_test_capture.sh --scenario combo
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

if [[ -x "${REPO_ROOT}/venv/bin/python" ]]; then
  PYTHON_BIN="${REPO_ROOT}/venv/bin/python"
elif python3 -c 'import evdev' >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  printf 'No suitable Python with evdev found. Expected %s or python3 with evdev.\n' "${REPO_ROOT}/venv/bin/python" >&2
  exit 1
fi

exec "${PYTHON_BIN}" -m bluetooth_2_usb.test_harness capture "$@"
