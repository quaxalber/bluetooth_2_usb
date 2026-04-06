#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

load_readonly_config
SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"

DEVICE="${B2U_PERSIST_DEVICE:-}"
PERSIST_MOUNT="${B2U_PERSIST_MOUNT:-$B2U_PERSIST_MOUNT_FIXED}"
BLUETOOTH_SUBDIR="$B2U_PERSIST_BLUETOOTH_SUBDIR"
NO_ENABLE=0

usage() {
  cat <<EOF
Usage: sudo ./setup_persistent_bluetooth_state.sh [options]
  --device <path>         Block device to mount persistently
  --no-enable             Only prepare config and units; do not activate them now
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) require_value "$1" "${2:-}"; DEVICE="$2"; shift 2 ;;
    --no-enable) NO_ENABLE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "persistent_bluetooth_setup"
require_commands blkid cp mkdir mount mountpoint python3 systemctl systemd-escape

if ! machine_id_valid; then
  fail "/etc/machine-id is missing or invalid. Persistent read-only mode requires a stable machine-id."
fi

if [[ -z "$DEVICE" && -z "${B2U_PERSIST_SPEC:-}" ]]; then
  if mountpoint -q "$PERSIST_MOUNT"; then
    source_spec="$(findmnt -n -o SOURCE --target "$PERSIST_MOUNT" 2>/dev/null || true)"
    [[ -n "$source_spec" ]] || fail "Could not determine the backing source for ${PERSIST_MOUNT}. Provide --device."
    if [[ -b "$source_spec" ]]; then
      DEVICE="$source_spec"
    else
      PERSIST_SPEC="$source_spec"
    fi
  else
    fail "Provide --device or prepare an existing persistent mount first."
  fi
fi

if [[ -n "$DEVICE" ]]; then
  detected_type="$(blkid -s TYPE -o value "$DEVICE" 2>/dev/null || true)"
  [[ -n "$detected_type" ]] || fail "No filesystem detected on ${DEVICE}. Create an ext4 filesystem first, then rerun this script."
  [[ "$detected_type" == "ext4" ]] || fail "Expected ext4 on ${DEVICE}, got ${detected_type}"
  PERSIST_SPEC="$(persist_spec_from_device "$DEVICE")"
else
  PERSIST_SPEC="${PERSIST_SPEC:-${B2U_PERSIST_SPEC:-}}"
fi

[[ -n "$PERSIST_SPEC" ]] || fail "Could not determine persistent mount source."

PERSIST_BLUETOOTH_DIR="${PERSIST_MOUNT}/${BLUETOOTH_SUBDIR}"
mkdir -p "$PERSIST_MOUNT"
mkdir -p "$PERSIST_BLUETOOTH_DIR"

write_persist_mount_unit "$PERSIST_SPEC" "$PERSIST_MOUNT" "ext4"
write_bluetooth_bind_mount_unit "$PERSIST_BLUETOOTH_DIR"
install_bluetooth_persist_dropin
write_readonly_config "disabled" "$PERSIST_MOUNT" "$PERSIST_BLUETOOTH_DIR" "$PERSIST_SPEC" "$DEVICE"

if [[ $NO_ENABLE -eq 1 ]]; then
  systemctl daemon-reload
  ok "Persistent Bluetooth state configuration prepared"
  cat <<EOF

Next steps:
1. Review the generated mount configuration.
2. Run:
   sudo systemctl enable --now $(persist_mount_unit_name "$PERSIST_MOUNT") var-lib-bluetooth.mount
3. Then enable read-only mode with:
   sudo ${SCRIPT_DIR}/enable_readonly_overlayfs.sh --mode persistent
EOF
  exit 0
fi

if service_installed; then
  systemctl stop "${B2U_SERVICE_UNIT}" || true
fi
systemctl stop bluetooth.service 2>/dev/null || true

systemctl daemon-reload
systemctl enable --now "$(persist_mount_unit_name "$PERSIST_MOUNT")"

if [[ -d /var/lib/bluetooth ]]; then
  seed_lock_dir="${PERSIST_BLUETOOTH_DIR}/.b2u-seed.lock"
  seed_marker="${PERSIST_BLUETOOTH_DIR}/.b2u-seeded"
  if mkdir "$seed_lock_dir" 2>/dev/null; then
    cleanup_seed_lock() {
      rmdir "$seed_lock_dir" 2>/dev/null || true
    }
    trap cleanup_seed_lock EXIT
    if [[ ! -e "$seed_marker" ]] && [[ -z "$(find "$PERSIST_BLUETOOTH_DIR" -mindepth 1 -maxdepth 1 ! -name '.b2u-seed.lock' ! -name '.b2u-seeded' ! -name '.b2u-persistent-state' 2>/dev/null | head -n 1)" ]]; then
      cp -a /var/lib/bluetooth/. "$PERSIST_BLUETOOTH_DIR"/
      touch "$seed_marker"
    fi
    cleanup_seed_lock
    trap - EXIT
  fi
fi
touch "${PERSIST_BLUETOOTH_DIR}/.b2u-persistent-state"

if mountpoint -q /var/lib/bluetooth; then
  current_source="$(findmnt -n -o SOURCE --target /var/lib/bluetooth 2>/dev/null || true)"
  if [[ "$current_source" != "$PERSIST_BLUETOOTH_DIR" ]]; then
    umount /var/lib/bluetooth || true
  fi
fi
mkdir -p /var/lib/bluetooth

systemctl enable --now var-lib-bluetooth.mount
systemctl start bluetooth.service 2>/dev/null || true
if service_installed; then
  systemctl restart "${B2U_SERVICE_UNIT}" || true
fi

ok "Persistent Bluetooth state is active at ${PERSIST_BLUETOOTH_DIR}"
