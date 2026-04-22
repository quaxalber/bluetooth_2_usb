#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}"
# shellcheck source=./lib/paths.sh
source "${SCRIPTS_DIR}/lib/paths.sh"
# shellcheck source=./lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"
# shellcheck source=./lib/readonly.sh
source "${SCRIPTS_DIR}/lib/readonly.sh"

usage() {
  cat <<EOF
Usage: sudo ./scripts/readonly-enable.sh

Enable Raspberry Pi OS OverlayFS with persistent Bluetooth state.

Run ./scripts/readonly-setup.sh first to prepare the
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
require_commands dpkg-query raspi-config
load_readonly_config

if ! machine_id_valid; then
  fail "/etc/machine-id is missing or invalid. Persistent read-only mode requires a stable machine-id."
fi
if [[ -z "${B2U_PERSIST_SPEC:-}" ]]; then
  fail "Run ./scripts/readonly-setup.sh --device /dev/... before enabling read-only mode."
fi
if ! bluetooth_state_persistent; then
  fail "Persistent Bluetooth state is not active. Run ./scripts/readonly-setup.sh --device /dev/... first."
fi

if [[ "$(overlay_status)" != "enabled" ]]; then
  if ! raspi-config nonint enable_overlayfs; then
    fail "Failed to enable OverlayFS through raspi-config."
  fi
fi

if ! readonly_stack_packages_healthy; then
  warn "OverlayFS package state is incomplete:"
  readonly_stack_package_report
  fail "OverlayFS may be toggled on, but package setup did not complete cleanly. Repair the package state before rebooting. On current Raspberry Pi OS releases this can require setting MODULES=most in /etc/initramfs-tools/initramfs.conf, then rerunning sudo dpkg --configure -a."
fi

write_readonly_config "persistent" "$B2U_PERSIST_MOUNT" "$B2U_PERSIST_BLUETOOTH_DIR" "$B2U_PERSIST_SPEC" "$B2U_PERSIST_DEVICE"
ok "OverlayFS has been enabled"
warn "Boot partition read-only mode is intentionally not changed by this script."
warn "Persistent read-only mode is configured. Reboot, then run ./scripts/smoketest.sh --verbose and verify reconnect behavior."
