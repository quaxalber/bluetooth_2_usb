#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=./lib/readonly.sh
source "${SCRIPT_DIR}/lib/readonly.sh"

usage() {
  cat <<EOF
Usage: sudo ./scripts/enable_readonly_overlayfs.sh

Enable Raspberry Pi OS OverlayFS with persistent Bluetooth state.

Run ./scripts/setup_persistent_bluetooth_state.sh first to prepare the
writable ext4 mount and bind-mount /var/lib/bluetooth.
EOF
}

case "${1:-}" in
  "") ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    fail "Unknown option: $1"
    ;;
esac

ensure_root
prepare_log "readonly_enable"
require_commands raspi-config
load_readonly_config

if ! machine_id_valid; then
  fail "/etc/machine-id is missing or invalid. Persistent read-only mode requires a stable machine-id."
fi
if [[ -z "${B2U_PERSIST_SPEC:-}" ]]; then
  fail "Run ./scripts/setup_persistent_bluetooth_state.sh --device /dev/... before enabling read-only mode."
fi
if ! bluetooth_state_persistent; then
  fail "Persistent Bluetooth state is not active. Run ./scripts/setup_persistent_bluetooth_state.sh --device /dev/... first."
fi

write_readonly_config "persistent" "$B2U_PERSIST_MOUNT" "$B2U_PERSIST_BLUETOOTH_DIR" "$B2U_PERSIST_SPEC" "$B2U_PERSIST_DEVICE"

if [[ "$(overlay_status)" == "enabled" ]]; then
  ok "OverlayFS is already enabled"
else
  raspi-config nonint enable_overlayfs
  ok "OverlayFS has been enabled"
fi

warn "Boot partition read-only mode is intentionally not changed by this script."
warn "Persistent read-only mode is configured. Reboot, then run ./scripts/smoke_test.sh --verbose and verify reconnect behavior."
