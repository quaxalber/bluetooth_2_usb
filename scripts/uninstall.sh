#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=./lib/install.sh
source "${SCRIPT_DIR}/lib/install.sh"
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
  systemctl stop "${B2U_SERVICE_UNIT}" || true
  if systemctl is-active --quiet "${B2U_SERVICE_UNIT}"; then
    systemctl kill --kill-who=all "${B2U_SERVICE_UNIT}" || true
    sleep 1
  fi
  systemctl disable "${B2U_SERVICE_UNIT}" || true
  systemctl reset-failed "${B2U_SERVICE_UNIT}" 2>/dev/null || true
fi

rm -f "/etc/systemd/system/${B2U_SERVICE_UNIT}"
rm -f "$B2U_ENV_FILE"
rm -f "$B2U_READONLY_ENV_FILE"
rm -f /usr/local/bin/bluetooth_2_usb
remove_bluetooth_persist_dropin
remove_bluetooth_bind_mount_unit
remove_persist_mount_unit "$B2U_PERSIST_MOUNT"
systemctl daemon-reload || true
systemctl disable --now var-lib-bluetooth.mount 2>/dev/null || true

if mountpoint -q /var/lib/bluetooth; then
  umount /var/lib/bluetooth || true
fi
if [[ -n "${B2U_PERSIST_MOUNT:-}" ]] && mountpoint -q "$B2U_PERSIST_MOUNT"; then
  persist_mount_unit=""
  persist_mount_unit="$(persist_mount_unit_name "$B2U_PERSIST_MOUNT")"
  systemctl disable --now "$persist_mount_unit" 2>/dev/null || true
  umount "$B2U_PERSIST_MOUNT" || true
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

ok "Uninstall complete"
info "The checkout at ${B2U_INSTALL_DIR} was left in place."
