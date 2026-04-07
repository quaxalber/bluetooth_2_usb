#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=./lib/common.sh
source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

PURGE=0
REVERT_BOOT=0
NO_REBOOT=0

usage() {
  cat <<EOF
Usage: sudo ./uninstall.sh [options]
  --purge             Remove the installation directory
  --revert-boot       Remove b2u boot configuration changes
  --no-reboot         Do not prompt for reboot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge)
      PURGE=1
      shift
      ;;
    --revert-boot)
      REVERT_BOOT=1
      shift
      ;;
    --no-reboot)
      NO_REBOOT=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) fail "Unknown option: $1" ;;
  esac
done

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
  restore_boot_restore_snapshot "$CONFIG_TXT" "$CMDLINE_TXT"
  clear_boot_restore_snapshot
  ok "Reverted boot configuration"
fi

if [[ $PURGE -eq 1 ]]; then
  rm -rf "$B2U_INSTALL_DIR"
  ok "Removed ${B2U_INSTALL_DIR}"
fi

if [[ $NO_REBOOT -eq 0 ]]; then
  if [[ -t 0 ]]; then
    read -r -p "Reboot now? [y/N] " answer || answer=""
    if [[ "${answer,,}" == "y" ]]; then
      sync
      reboot
    fi
  else
    info "Skipping reboot prompt because stdin is not interactive"
  fi
fi

ok "Uninstall complete"
