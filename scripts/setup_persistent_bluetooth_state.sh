#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

load_readonly_config

DEVICE="${B2U_PERSIST_DEVICE:-}"
PERSIST_MOUNT="${B2U_PERSIST_MOUNT:-$B2U_DEFAULT_PERSIST_MOUNT}"
BLUETOOTH_SUBDIR="$B2U_DEFAULT_PERSIST_BLUETOOTH_SUBDIR"
FS_TYPE="ext4"
FORMAT=0
LABEL="B2U_PERSIST"
NO_ENABLE=0

usage() {
  cat <<EOF
Usage: sudo ./setup_persistent_bluetooth_state.sh [options]
  --device <path>         Block device to mount persistently
  --mount <path>          Persistent mount point. Default: ${PERSIST_MOUNT}
  --bluetooth-subdir <n>  State directory below the persistent mount. Default: ${BLUETOOTH_SUBDIR}
  --fs-type <type>        Filesystem type. Default: ${FS_TYPE}
  --format                Format the device before use
  --label <name>          Filesystem label used with --format. Default: ${LABEL}
  --no-enable             Only prepare config and units; do not activate them now
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) require_value "$1" "${2:-}"; DEVICE="$2"; shift 2 ;;
    --mount) require_value "$1" "${2:-}"; PERSIST_MOUNT="$2"; shift 2 ;;
    --bluetooth-subdir) require_value "$1" "${2:-}"; BLUETOOTH_SUBDIR="$2"; shift 2 ;;
    --fs-type) require_value "$1" "${2:-}"; FS_TYPE="$2"; shift 2 ;;
    --format) FORMAT=1; shift ;;
    --label) require_value "$1" "${2:-}"; LABEL="$2"; shift 2 ;;
    --no-enable) NO_ENABLE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "persistent_bluetooth_setup"
require_commands blkid cp mkdir mount mountpoint python3 systemctl systemd-escape

if [[ "$FS_TYPE" != "ext4" ]]; then
  fail "Only ext4 is supported for persistent Bluetooth state at the moment."
fi

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

if [[ $FORMAT -eq 1 ]]; then
  [[ -n "$DEVICE" ]] || fail "--format requires --device"
  require_commands mkfs.ext4
  mkfs.ext4 -F -L "$LABEL" "$DEVICE"
fi

if [[ -n "$DEVICE" ]]; then
  detected_type="$(blkid -s TYPE -o value "$DEVICE" 2>/dev/null || true)"
  [[ -n "$detected_type" ]] || fail "No filesystem detected on ${DEVICE}. Use --format to create one."
  [[ "$detected_type" == "$FS_TYPE" ]] || fail "Expected ${FS_TYPE} on ${DEVICE}, got ${detected_type}"
  PERSIST_SPEC="$(persist_spec_from_device "$DEVICE")"
else
  PERSIST_SPEC="${PERSIST_SPEC:-${B2U_PERSIST_SPEC:-}}"
fi

[[ -n "$PERSIST_SPEC" ]] || fail "Could not determine persistent mount source."

PERSIST_BLUETOOTH_DIR="${PERSIST_MOUNT}/${BLUETOOTH_SUBDIR}"
mkdir -p "$PERSIST_MOUNT"
mkdir -p "$PERSIST_BLUETOOTH_DIR"

write_persist_mount_unit "$PERSIST_SPEC" "$PERSIST_MOUNT" "$FS_TYPE"
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
   sudo ${B2U_DEFAULT_INSTALL_DIR}/scripts/enable_readonly_overlayfs.sh --mode persistent
EOF
  exit 0
fi

if service_installed; then
  systemctl stop "${B2U_DEFAULT_SERVICE_NAME}.service" || true
fi
systemctl stop bluetooth.service 2>/dev/null || true

systemctl daemon-reload
systemctl enable --now "$(persist_mount_unit_name "$PERSIST_MOUNT")"

if [[ -d /var/lib/bluetooth ]] && [[ -z "$(find "$PERSIST_BLUETOOTH_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]]; then
  cp -a /var/lib/bluetooth/. "$PERSIST_BLUETOOTH_DIR"/
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
  systemctl restart "${B2U_DEFAULT_SERVICE_NAME}.service" || true
fi

ok "Persistent Bluetooth state is active at ${PERSIST_BLUETOOTH_DIR}"
