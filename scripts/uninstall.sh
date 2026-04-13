#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/paths.sh
source "${SCRIPT_DIR}/lib/paths.sh"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=./lib/install.sh
source "${SCRIPT_DIR}/lib/install.sh"
# shellcheck source=./lib/bluetooth.sh
source "${SCRIPT_DIR}/lib/bluetooth.sh"
# shellcheck source=./lib/readonly.sh
source "${SCRIPT_DIR}/lib/readonly.sh"

usage() {
  cat <<EOF
Usage: sudo ./scripts/uninstall.sh

Remove the managed system integration for Bluetooth-2-USB:
- stop and disable ${B2U_SERVICE_UNIT}
- remove systemd units, wrapper, and env files
- remove persistent Bluetooth-state mount integration

The checkout at ${B2U_INSTALL_DIR} is left in place.
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
prepare_log "uninstall"
load_readonly_config

if service_installed || [[ "$(systemctl show -P LoadState "${B2U_SERVICE_UNIT}" 2>/dev/null || true)" != "not-found" ]]; then
  systemctl stop "${B2U_SERVICE_UNIT}" || fail "Failed to stop ${B2U_SERVICE_UNIT}"
  if systemctl is-active --quiet "${B2U_SERVICE_UNIT}"; then
    systemctl kill --kill-who=all "${B2U_SERVICE_UNIT}" || fail "Failed to kill ${B2U_SERVICE_UNIT}"
    sleep 1
  fi
  systemctl disable "${B2U_SERVICE_UNIT}" || fail "Failed to disable ${B2U_SERVICE_UNIT}"
  systemctl reset-failed "${B2U_SERVICE_UNIT}" 2>/dev/null || true
fi

rm -f "/etc/systemd/system/${B2U_SERVICE_UNIT}"
rm -f "$B2U_ENV_FILE"
rm -f "$B2U_READONLY_ENV_FILE"
rm -f /usr/local/bin/bluetooth_2_usb
remove_bluetooth_persist_dropin
remove_bluetooth_bind_mount_unit
remove_persist_mount_unit "$B2U_PERSIST_MOUNT"
systemctl daemon-reload || fail "Failed to reload systemd units"
systemctl disable --now var-lib-bluetooth.mount 2>/dev/null || true

if findmnt -rn /var/lib/bluetooth >/dev/null 2>&1; then
  systemctl stop bluetooth.service || fail "Failed to stop bluetooth.service before unmounting /var/lib/bluetooth"
  if findmnt -rn /var/lib/bluetooth >/dev/null 2>&1; then
    umount /var/lib/bluetooth || fail "Failed to unmount /var/lib/bluetooth"
  fi
fi
if [[ -n "${B2U_PERSIST_MOUNT:-}" ]] && findmnt -rn "$B2U_PERSIST_MOUNT" >/dev/null 2>&1; then
  persist_mount_unit=""
  persist_mount_unit="$(persist_mount_unit_name "$B2U_PERSIST_MOUNT")"
  systemctl disable --now "$persist_mount_unit" 2>/dev/null || true
  if findmnt -rn "$B2U_PERSIST_MOUNT" >/dev/null 2>&1; then
    umount "$B2U_PERSIST_MOUNT" || fail "Failed to unmount ${B2U_PERSIST_MOUNT}"
  fi
fi

if [[ -d /sys/kernel/config/usb_gadget ]]; then
  shopt -s nullglob
  for gadget in /sys/kernel/config/usb_gadget/adafruit-blinka /sys/kernel/config/usb_gadget/bluetooth_2_usb*; do
    [[ -d "$gadget" ]] || continue
    [[ -f "${gadget}/UDC" ]] && : >"${gadget}/UDC" || true
    find "${gadget}/configs" -type l -exec rm -f {} + 2>/dev/null || true
    rm -rf "${gadget}/functions/"* 2>/dev/null || true
    find "${gadget}/configs" -mindepth 1 -maxdepth 1 -type d -exec rmdir {} + 2>/dev/null || true
    rmdir "$gadget" 2>/dev/null || true
  done
  shopt -u nullglob
fi

systemctl daemon-reload || fail "Failed to reload systemd after cleanup"

[[ ! -f "/etc/systemd/system/${B2U_SERVICE_UNIT}" ]] || fail "Service unit file still exists after uninstall"
[[ ! -f "$B2U_ENV_FILE" ]] || fail "Runtime config file still exists after uninstall"
[[ ! -f "$B2U_READONLY_ENV_FILE" ]] || fail "Read-only config file still exists after uninstall"
[[ ! -f /usr/local/bin/bluetooth_2_usb ]] || fail "CLI wrapper still exists after uninstall"
[[ ! -e "$B2U_BLUETOOTH_BIND_MOUNT_UNIT" ]] || fail "Bluetooth bind-mount unit still exists after uninstall"
[[ ! -e "$B2U_BLUETOOTH_SERVICE_DROPIN" ]] || fail "bluetooth.service drop-in still exists after uninstall"

if systemctl is-enabled "${B2U_SERVICE_UNIT}" >/dev/null 2>&1; then
  fail "${B2U_SERVICE_UNIT} is still enabled after uninstall"
fi

ok "Uninstall complete"
info "The checkout at ${B2U_INSTALL_DIR} was left in place."
