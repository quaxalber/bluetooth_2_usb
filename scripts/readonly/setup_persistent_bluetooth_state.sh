#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../lib/paths.sh
source "${SCRIPTS_DIR}/lib/paths.sh"
# shellcheck source=../lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"
# shellcheck source=../lib/install.sh
source "${SCRIPTS_DIR}/lib/install.sh"
# shellcheck source=../lib/readonly.sh
source "${SCRIPTS_DIR}/lib/readonly.sh"

load_readonly_config

DEVICE=""
PERSIST_MOUNT="${B2U_PERSIST_MOUNT:-$B2U_PERSIST_MOUNT_PATH}"
BLUETOOTH_SUBDIR="$B2U_PERSIST_BLUETOOTH_SUBDIR"

usage() {
  cat <<EOF
Usage: sudo ./scripts/readonly/setup_persistent_bluetooth_state.sh --device <path>

Prepare and activate persistent Bluetooth state on a writable ext4 filesystem.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      require_value "$1" "${2:-}"
      DEVICE="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

ensure_root
prepare_log "persistent_bluetooth_setup"
require_commands blkid cp mkdir mount mountpoint systemctl systemd-escape
[[ -n "$DEVICE" ]] || fail "Pass --device /dev/YOUR-PARTITION for the writable ext4 filesystem."

if ! machine_id_valid; then
  fail "/etc/machine-id is missing or invalid. Persistent read-only mode requires a stable machine-id."
fi

detected_type="$(blkid -s TYPE -o value "$DEVICE" 2>/dev/null || true)"
[[ -n "$detected_type" ]] || fail "No filesystem detected on ${DEVICE}. Create an ext4 filesystem first, then rerun this script."
[[ "$detected_type" == "ext4" ]] || fail "Expected ext4 on ${DEVICE}, got ${detected_type}"

PERSIST_SPEC="$(persist_spec_from_device "$DEVICE")"
PERSIST_BLUETOOTH_DIR="${PERSIST_MOUNT}/${BLUETOOTH_SUBDIR}"
PERSIST_MOUNT_UNIT="$(persist_mount_unit_name "$PERSIST_MOUNT")"
mkdir -p "$PERSIST_MOUNT"

write_persist_mount_unit "$PERSIST_SPEC" "$PERSIST_MOUNT" "ext4"
write_bluetooth_bind_mount_unit "$PERSIST_BLUETOOTH_DIR"
install_bluetooth_persist_dropin
write_readonly_config "disabled" "$PERSIST_MOUNT" "$PERSIST_BLUETOOTH_DIR" "$PERSIST_SPEC" "$DEVICE"

if service_installed; then
  systemctl stop "${B2U_SERVICE_UNIT}" || fail "Failed to stop ${B2U_SERVICE_UNIT} before migrating Bluetooth state"
fi
systemctl stop bluetooth.service || fail "Failed to stop bluetooth.service before migrating Bluetooth state"

systemctl daemon-reload
if mountpoint -q "$PERSIST_MOUNT"; then
  systemctl stop "$PERSIST_MOUNT_UNIT" 2>/dev/null || true
  if mountpoint -q "$PERSIST_MOUNT"; then
    umount "$PERSIST_MOUNT" || fail "Failed to unmount ${PERSIST_MOUNT} before switching the persistent mount source"
  fi
fi
systemctl enable --now "$PERSIST_MOUNT_UNIT"
mkdir -p "$PERSIST_BLUETOOTH_DIR"

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
  else
    fail "Failed to acquire seed lock ${seed_lock_dir} for ${PERSIST_BLUETOOTH_DIR}"
  fi
fi
touch "${PERSIST_BLUETOOTH_DIR}/.b2u-persistent-state"

if mountpoint -q /var/lib/bluetooth; then
  current_source="$(findmnt -n -o SOURCE --target /var/lib/bluetooth 2>/dev/null || true)"
  if [[ "$current_source" != "$PERSIST_BLUETOOTH_DIR" ]]; then
    umount /var/lib/bluetooth || fail "Failed to unmount /var/lib/bluetooth before enabling the persistent bind mount"
  fi
fi
mkdir -p /var/lib/bluetooth

systemctl enable --now var-lib-bluetooth.mount
systemctl start bluetooth.service || fail "Failed to start bluetooth.service after enabling the persistent bind mount"
systemctl is-active --quiet bluetooth.service || fail "bluetooth.service did not come back up after enabling the persistent bind mount"
if service_installed; then
  systemctl restart "${B2U_SERVICE_UNIT}" || fail "Failed to restart ${B2U_SERVICE_UNIT} after enabling the persistent bind mount"
  systemctl is-active --quiet "${B2U_SERVICE_UNIT}" || fail "${B2U_SERVICE_UNIT} did not come back up after enabling the persistent bind mount"
fi

ok "Persistent Bluetooth state is active at ${PERSIST_BLUETOOTH_DIR}"
