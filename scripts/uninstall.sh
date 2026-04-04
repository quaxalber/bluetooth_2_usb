#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

INSTALL_DIR="$B2U_DEFAULT_INSTALL_DIR"
SERVICE_NAME="$B2U_DEFAULT_SERVICE_NAME"
PURGE=0
REVERT_BOOT=0
NO_REBOOT=0

usage() {
  cat <<EOF
Usage: sudo ./uninstall.sh [options]
  --dir <path>        Install directory. Default: ${B2U_DEFAULT_INSTALL_DIR}
  --service <name>    Service name. Default: ${B2U_DEFAULT_SERVICE_NAME}
  --purge             Remove the installation directory
  --revert-boot       Remove b2u boot configuration changes
  --no-reboot         Do not prompt for reboot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --service) SERVICE_NAME="$2"; shift 2 ;;
    --purge) PURGE=1; shift ;;
    --revert-boot) REVERT_BOOT=1; shift ;;
    --no-reboot) NO_REBOOT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "uninstall"
load_readonly_config

if service_installed || [[ "$(systemctl show -P LoadState "${SERVICE_NAME}.service" 2>/dev/null || true)" != "not-found" ]]; then
  systemctl stop "${SERVICE_NAME}.service" || true
  if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    systemctl kill --kill-who=all "${SERVICE_NAME}.service" || true
    sleep 1
  fi
  systemctl disable "${SERVICE_NAME}.service" || true
  systemctl reset-failed "${SERVICE_NAME}.service" 2>/dev/null || true
fi
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
rm -f "$B2U_DEFAULT_ENV_FILE"
rm -f "$B2U_READONLY_ENV_FILE"
rm -f /usr/local/bin/bluetooth_2_usb
remove_bluetooth_persist_dropin
remove_bluetooth_bind_mount_unit
remove_persist_mount_unit
systemctl daemon-reload || true
if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
  systemctl kill --kill-who=all "${SERVICE_NAME}.service" || true
  sleep 1
fi
systemctl disable --now var-lib-bluetooth.mount 2>/dev/null || true

if mountpoint -q /var/lib/bluetooth; then
  umount /var/lib/bluetooth || true
fi
if [[ -n "${B2U_PERSIST_MOUNT:-}" ]] && mountpoint -q "$B2U_PERSIST_MOUNT"; then
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

if [[ $REVERT_BOOT -eq 1 ]]; then
  CONFIG_TXT="$(boot_config_path)"
  CMDLINE_TXT="$(boot_cmdline_path)"
  backup_file "$CONFIG_TXT"
  backup_file "$CMDLINE_TXT"
  remove_dwc2_overlay "$CONFIG_TXT"
  remove_modules_load_entries "$CMDLINE_TXT"
  ok "Reverted boot configuration"
fi

if [[ $PURGE -eq 1 ]]; then
  rm -rf "$INSTALL_DIR"
  ok "Removed ${INSTALL_DIR}"
fi

if [[ $NO_REBOOT -eq 0 ]]; then
  read -r -p "Reboot now? [y/N] " answer
  if [[ "${answer,,}" == "y" ]]; then
    sync
    reboot
  fi
fi

ok "Uninstall complete"
