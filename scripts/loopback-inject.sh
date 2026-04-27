#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}"
# shellcheck source=./lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"
# shellcheck source=./lib/paths.sh
source "${SCRIPTS_DIR}/lib/paths.sh"

PYTHON_BIN="${B2U_INSTALL_DIR}/venv/bin/python"
SERVICE_SETTLE_SEC="${B2U_LOOPBACK_SERVICE_SETTLE_SEC:-10}"

usage() {
  cat <<EOF
Usage: sudo ${B2U_INSTALL_DIR}/scripts/loopback-inject.sh [test_harness inject options]

Run the Pi-side loopback injector using the managed virtual environment.
Example:
  sudo ${B2U_INSTALL_DIR}/scripts/loopback-inject.sh --scenario combo
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

[[ -x "${PYTHON_BIN}" ]] || fail "Managed Python not found: ${PYTHON_BIN}"

wait_for_service_settle() {
  local active_since_us
  local now_us
  local age_us
  local settle_us
  local remaining_sec

  command -v systemctl >/dev/null 2>&1 || return 0
  [[ "${SERVICE_SETTLE_SEC}" != "0" ]] || return 0
  systemctl is-active --quiet bluetooth_2_usb.service || return 0

  active_since_us="$(systemctl show bluetooth_2_usb.service \
    --property=ActiveEnterTimestampMonotonic --value 2>/dev/null || true)"
  [[ -n "${active_since_us}" && "${active_since_us}" != "0" ]] || return 0

  now_us="$(awk '{ printf "%.0f", $1 * 1000000 }' /proc/uptime)"
  settle_us="$(awk -v sec="${SERVICE_SETTLE_SEC}" 'BEGIN { printf "%.0f", sec * 1000000 }')"
  age_us=$((now_us - active_since_us))
  ((age_us < settle_us)) || return 0

  remaining_sec="$(awk -v remaining_us="$((settle_us - age_us))" \
    'BEGIN { printf "%.3f", remaining_us / 1000000 }')"
  sleep "${remaining_sec}"
}

wait_for_service_settle

exec "${PYTHON_BIN}" -m bluetooth_2_usb.test_harness inject "$@"
