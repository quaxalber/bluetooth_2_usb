#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}"
# shellcheck source=./lib/paths.sh
source "${SCRIPTS_DIR}/lib/paths.sh"
# shellcheck source=./lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"
# shellcheck source=./lib/boot.sh
source "${SCRIPTS_DIR}/lib/boot.sh"
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

if ! readonly_stack_packages_bootstrap_safe; then
  warn "OverlayFS package state is incomplete:"
  readonly_stack_package_report
  fail "OverlayFS package setup did not complete cleanly. Repair the package state before enabling read-only mode. On current Raspberry Pi OS releases this can require setting MODULES=most in /etc/initramfs-tools/initramfs.conf, then rerunning sudo dpkg --configure -a."
fi

KERNEL_RELEASE="$(current_kernel_release)"
CONFIGURED_KERNEL_IMAGE="$(configured_kernel_image)"
CONFIGURED_INITRAMFS_FILE="$(configured_initramfs_file)"
EXPECTED_BOOT_INITRAMFS_FILE="$(expected_boot_initramfs_file || true)"
VERSIONED_INITRDS="$(versioned_initrd_candidates "$KERNEL_RELEASE" | tr '\n' ' ' | sed 's/[[:space:]]*$//')"

info "Kernel release: ${KERNEL_RELEASE}"
info "Configured kernel image: ${CONFIGURED_KERNEL_IMAGE}"
info "Explicit initramfs entry: ${CONFIGURED_INITRAMFS_FILE:-<none>}"
info "Expected boot initramfs file: ${EXPECTED_BOOT_INITRAMFS_FILE:-<none>}"
info "Versioned initramfs candidates: ${VERSIONED_INITRDS:-<none>}"

OVERLAY_STATUS_NOW="$(overlay_status)"
if readonly_stack_packages_missing; then
  info "OverlayFS prerequisites are not fully installed yet; raspi-config will install or finish them now."
fi
if [[ "$OVERLAY_STATUS_NOW" != "enabled" ]]; then
  if ! raspi-config nonint enable_overlayfs; then
    fail "Failed to enable OverlayFS through raspi-config."
  fi
fi

if ! readonly_stack_packages_healthy; then
  warn "OverlayFS package state is incomplete:"
  readonly_stack_package_report
  fail "OverlayFS package setup did not complete cleanly. Repair the package state before enabling read-only mode. On current Raspberry Pi OS releases this can require setting MODULES=most in /etc/initramfs-tools/initramfs.conf, then rerunning sudo dpkg --configure -a."
fi

if ! BOOT_INITRAMFS_TARGET_PATH="$(ensure_bootable_initramfs_for_current_kernel)"; then
  fail "Failed to prepare the boot initramfs for read-only mode. Fix the kernel or initramfs setup above, then rerun ./scripts/readonly-enable.sh."
fi
ok "Boot initramfs is ready at ${BOOT_INITRAMFS_TARGET_PATH}"

OVERLAY_STATUS_NOW="$(overlay_status)"
if [[ "$OVERLAY_STATUS_NOW" != "enabled" ]]; then
  if [[ "$(overlay_configured_status)" == "enabled" ]]; then
    warn "OverlayFS is configured for the next boot, but the live root is still writable until reboot."
  elif grep -Eq '(^| )overlayroot=tmpfs($| )' "$(boot_cmdline_path)" 2>/dev/null; then
    warn "OverlayFS enablement is pending reboot; $(boot_cmdline_path) contains overlayroot=tmpfs even though the live status still reports disabled."
  else
    fail "OverlayFS is still not configured after raspi-config completed."
  fi
fi

write_readonly_config "persistent" "$B2U_PERSIST_MOUNT" "$B2U_PERSIST_BLUETOOTH_DIR" "$B2U_PERSIST_SPEC" "$B2U_PERSIST_DEVICE"
ok "OverlayFS has been enabled"
warn "Boot partition read-only mode is intentionally not changed by this script."
warn "Persistent read-only mode is configured. Reboot, then run ./scripts/smoketest.sh --verbose and verify reconnect behavior."
