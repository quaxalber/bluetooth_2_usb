#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}"
REPO_ROOT="$(cd -- "${SCRIPTS_DIR}/.." && pwd)"
PYTHON_BIN=""
# shellcheck source=./lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"

usage() {
  cat <<EOF
Usage: ./scripts/loopback-capture.sh [test_harness capture options]

Capture relay reports from the host-side gadget HID devices.
On Linux, install the host hidapi udev rule first if unprivileged access fails.
Example:
  ./scripts/loopback-capture.sh --scenario combo
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

if [[ -n "${HOST_CAPTURE_PYTHON:-}" ]]; then
  PYTHON_BIN="${HOST_CAPTURE_PYTHON}"
elif [[ -x "${REPO_ROOT}/venv/bin/python" ]] && "${REPO_ROOT}/venv/bin/python" -c 'import hid' >/dev/null 2>&1; then
  PYTHON_BIN="${REPO_ROOT}/venv/bin/python"
elif python3 -c 'import hid' >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif python -c 'import hid' >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  fail "No suitable Python with hidapi found. Set HOST_CAPTURE_PYTHON or install the Python package 'hidapi'."
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON_BIN}" -m bluetooth_2_usb.test_harness capture "$@"
