#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/paths.sh
source "${SCRIPT_DIR}/lib/paths.sh"

PYTHON_BIN="${B2U_INSTALL_DIR}/venv/bin/python"

usage() {
  cat <<EOF
Usage: sudo ${B2U_INSTALL_DIR}/scripts/pi_relay_test_inject.sh [test_harness inject options]

Run the Pi-side loopback injector using the managed virtual environment.
Example:
  sudo ${B2U_INSTALL_DIR}/scripts/pi_relay_test_inject.sh --scenario combo
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

[[ -x "${PYTHON_BIN}" ]] || {
  printf 'Managed Python not found: %s\n' "${PYTHON_BIN}" >&2
  exit 1
}

exec "${PYTHON_BIN}" -m bluetooth_2_usb.test_harness inject "$@"
