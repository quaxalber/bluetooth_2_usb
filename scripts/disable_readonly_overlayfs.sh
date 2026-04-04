#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

usage() {
  cat <<EOF
Usage: sudo ./disable_readonly_overlayfs.sh

Disables the Raspberry Pi OS OverlayFS root filesystem mode.
Any configured persistent Bluetooth mount remains in place.
EOF
}

case "${1:-}" in
  "" ) ;;
  -h|--help) usage; exit 0 ;;
  *) fail "Unknown option: $1" ;;
esac

ensure_root
prepare_log "readonly_disable"
require_commands raspi-config

load_readonly_config
raspi-config nonint disable_overlayfs
write_readonly_config "disabled" "$B2U_PERSIST_MOUNT" "$B2U_PERSIST_BLUETOOTH_DIR" "$B2U_PERSIST_SPEC" "$B2U_PERSIST_DEVICE"
ok "OverlayFS has been disabled"
warn "Persistent Bluetooth mount configuration was kept. Reboot to return to a writable root filesystem."
