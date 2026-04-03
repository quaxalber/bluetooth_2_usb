#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

MODE="easy"
PERSIST_DEVICE=""
PERSIST_MOUNT="$B2U_DEFAULT_PERSIST_MOUNT"
BLUETOOTH_SUBDIR="$B2U_DEFAULT_PERSIST_BLUETOOTH_SUBDIR"
FORMAT=0

usage() {
  cat <<EOF
Usage: sudo ./enable_readonly_overlayfs.sh [options]
  --mode <easy|persistent>   Read-only mode. Default: easy
  --persist-device <path>    Block device for persistent Bluetooth state
  --persist-mount <path>     Persistent mount point. Default: ${PERSIST_MOUNT}
  --bluetooth-subdir <name>  Bluetooth subdir on the persistent mount. Default: ${BLUETOOTH_SUBDIR}
  --format                   Format the persistent device as ext4 before use

Easy mode only enables OverlayFS and stores recovery snapshots on /boot.
Persistent mode additionally bind-mounts /var/lib/bluetooth from a writable ext4 mount.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --persist-device) PERSIST_DEVICE="$2"; shift 2 ;;
    --persist-mount) PERSIST_MOUNT="$2"; shift 2 ;;
    --bluetooth-subdir) BLUETOOTH_SUBDIR="$2"; shift 2 ;;
    --format) FORMAT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

[[ "$MODE" == "easy" || "$MODE" == "persistent" ]] || fail "Unsupported mode: ${MODE}"

ensure_root
prepare_log "readonly_enable"
require_commands raspi-config

snapshot_readonly_state

if [[ "$MODE" == "easy" ]]; then
  if bluetooth_state_persistent; then
    fail "Persistent Bluetooth state is already configured. Use --mode persistent or disable that setup first."
  fi
  readonly_warning_easy_mode
  write_readonly_config "easy" "$PERSIST_MOUNT" "${PERSIST_MOUNT}/${BLUETOOTH_SUBDIR}" "" ""
else
  if ! machine_id_valid; then
    fail "/etc/machine-id is missing or invalid. Persistent read-only mode requires a stable machine-id."
  fi

  setup_args=(--mount "$PERSIST_MOUNT" --bluetooth-subdir "$BLUETOOTH_SUBDIR")
  if [[ -n "$PERSIST_DEVICE" ]]; then
    setup_args+=(--device "$PERSIST_DEVICE")
  fi
  if [[ $FORMAT -eq 1 ]]; then
    setup_args+=(--format)
  fi

  bash "$(cd -- "$(dirname "$0")" && pwd)/setup_persistent_bluetooth_state.sh" "${setup_args[@]}"
  load_readonly_config
  write_readonly_config "persistent" "$B2U_PERSIST_MOUNT" "$B2U_PERSIST_BLUETOOTH_DIR" "$B2U_PERSIST_SPEC" "$B2U_PERSIST_DEVICE"
fi

if [[ "$(overlay_status)" == "enabled" ]]; then
  ok "OverlayFS is already enabled"
else
  raspi-config nonint enable_overlayfs
  ok "OverlayFS has been enabled"
fi

warn "Boot partition read-only mode is intentionally not changed by this script."
if [[ "$MODE" == "easy" ]]; then
  warn "Easy mode is best effort only. Reboot, then verify Bluetooth reconnects and relay behavior."
else
  warn "Persistent mode is configured. Reboot, then run smoke_test.sh --verbose and verify reconnect behavior."
fi
