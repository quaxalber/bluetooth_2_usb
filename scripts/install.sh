#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/paths.sh
source "${SCRIPT_DIR}/lib/paths.sh"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=./lib/boot.sh
source "${SCRIPT_DIR}/lib/boot.sh"
# shellcheck source=./lib/install.sh
source "${SCRIPT_DIR}/lib/install.sh"

usage() {
  cat <<EOF
Usage: sudo ./scripts/install.sh

Apply the current checkout in ${B2U_INSTALL_DIR} to the managed system install:
- patch the required boot settings
- rebuild the managed virtual environment
- install the systemd unit and CLI wrapper
- restart ${B2U_SERVICE_UNIT}
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
prepare_log "install"
require_commands apt-get awk grep git install python3 sed systemctl

[[ "$B2U_REPO_ROOT" == "$B2U_INSTALL_DIR" ]] || fail "Clone this repository to ${B2U_INSTALL_DIR} and run ./scripts/install.sh from there."
[[ -d "${B2U_INSTALL_DIR}/.git" ]] || fail "Expected a git checkout at ${B2U_INSTALL_DIR}."

BOOT_DIR="$(detect_boot_dir)"
CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
DWC2_MODE="$(dwc2_mode)"
OVERLAY_LINE="$(board_overlay_line "$MODEL")"
MODULES="$(required_boot_modules_csv)"
PRE_REBOOT_EXIT=3

info "Detected model: ${MODEL:-unknown}"
info "Using boot directory: ${BOOT_DIR}"
info "Detected dwc2 mode: ${DWC2_MODE}"

apt-get update -y
apt-get install -y --no-install-recommends git python3 python3-pip python3-venv python3-dev

normalize_dwc2_overlay "$CONFIG_TXT" "$OVERLAY_LINE"
normalize_modules_load "$CMDLINE_TXT" "$MODULES"
ok "Boot configuration updated"

if [[ "$DWC2_MODE" == "unknown" ]]; then
  warn "Could not determine whether dwc2 is built-in or modular; modules-load was set conservatively to ${MODULES}."
fi

if systemctl is-active --quiet "${B2U_SERVICE_UNIT}" 2>/dev/null; then
  info "Stopping ${B2U_SERVICE_UNIT} before rebuilding the managed installation"
  systemctl stop "${B2U_SERVICE_UNIT}" || fail "Failed to stop ${B2U_SERVICE_UNIT}"
fi

VENV_DIR="${B2U_INSTALL_DIR}/venv"
info "Rebuilding virtual environment at ${VENV_DIR}"
rebuild_venv_atomically "$VENV_DIR" "$B2U_INSTALL_DIR" || fail "Failed to rebuild virtual environment at ${VENV_DIR}. Restore from the latest .bak backup if needed."
ok "Virtual environment updated at ${VENV_DIR}"

install_service_unit
write_default_env_file
normalize_runtime_env_file
if ! "${VENV_DIR}/bin/python" -m bluetooth_2_usb.service_config --canonicalize-bools >/dev/null; then
  fail "Runtime config boolean canonicalization failed for ${B2U_ENV_FILE}."
fi
if ! "${VENV_DIR}/bin/python" -m bluetooth_2_usb.service_config --check >/dev/null; then
  fail "Runtime config validation failed for ${B2U_ENV_FILE}. Expected the structured B2U_* format."
fi
install_cli_wrapper
systemctl daemon-reload
activate_service_unit
ok "Service ${B2U_SERVICE_UNIT} enabled and started"

if "${VENV_DIR}/bin/python" -m bluetooth_2_usb --version >/dev/null; then
  ok "CLI version check succeeded"
else
  fail "CLI version check failed"
fi

set +e
"${VENV_DIR}/bin/python" -m bluetooth_2_usb --validate-env
validate_exit=$?
set -e

if [[ $validate_exit -eq 0 ]]; then
  ok "Environment validation passed"
elif [[ $validate_exit -eq $PRE_REBOOT_EXIT ]]; then
  warn "Environment validation reports missing runtime prerequisites until after reboot"
else
  fail "Environment validation failed with exit code ${validate_exit}"
fi

cat <<EOF

${BOLD}Next steps${NC}
1. Reboot the Pi so the updated boot configuration takes effect.
2. After reboot, run:
   sudo ${B2U_INSTALL_DIR}/scripts/smoke_test.sh
3. If you want persistent read-only operation afterwards, run:
   sudo ${B2U_INSTALL_DIR}/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-PARTITION
   sudo ${B2U_INSTALL_DIR}/scripts/enable_readonly_overlayfs.sh
EOF
