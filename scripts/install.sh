#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=./lib/common.sh
source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

REPO_URL="$(default_repo_url)"
REPO_BRANCH="$(default_repo_branch)"
NO_REBOOT=0

usage() {
  cat <<EOF
Usage: sudo ./install.sh [options]
  --repo <url|path>   Repository source. Default: current repo checkout
  --branch <name>     Branch/tag to install. Default: current branch
  --no-reboot         Do not prompt for reboot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      require_value "$1" "${2:-}"
      REPO_URL="$2"
      shift 2
      ;;
    --branch)
      require_value "$1" "${2:-}"
      REPO_BRANCH="$2"
      shift 2
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
prepare_log "install"
require_commands apt-get awk grep install sed systemctl

BOOT_DIR="$(detect_boot_dir)"
CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
DWC2_MODE="$(dwc2_mode)"
OVERLAY_LINE="$(board_overlay_line "$MODEL")"

info "Detected model: ${MODEL:-unknown}"
info "Using boot directory: ${BOOT_DIR}"
info "Detected dwc2 mode: ${DWC2_MODE}"

apt-get update -y
apt-get install -y --no-install-recommends git python3 python3-pip python3-venv python3-dev
require_commands git python3

BOOT_SNAPSHOT_ACTIVE=0
cleanup_on_failure() {
  local exit_code=$?
  trap - EXIT
  if [[ $exit_code -ne 0 && $BOOT_SNAPSHOT_ACTIVE -eq 1 ]]; then
    warn "Install failed; restoring original boot configuration"
    if ! restore_boot_restore_snapshot "$CONFIG_TXT" "$CMDLINE_TXT"; then
      warn "Failed to restore the managed boot configuration snapshot"
    fi
    if ! clear_boot_restore_snapshot; then
      warn "Failed to clear the managed boot configuration snapshot"
    fi
  fi
  exit "$exit_code"
}
trap cleanup_on_failure EXIT

backup_file "$CONFIG_TXT"
backup_file "$CMDLINE_TXT"
capture_boot_restore_snapshot "$CONFIG_TXT" "$CMDLINE_TXT"
BOOT_SNAPSHOT_ACTIVE=1
normalize_dwc2_overlay "$CONFIG_TXT" "$OVERLAY_LINE"

MODULES="libcomposite"
if [[ "$DWC2_MODE" == "module" ]]; then
  MODULES="dwc2,libcomposite"
fi
normalize_modules_load "$CMDLINE_TXT" "$MODULES"
ok "Boot configuration updated"

mkdir -p "$(dirname "$B2U_INSTALL_DIR")"
if [[ "$REPO_URL" == "$B2U_INSTALL_DIR" ]]; then
  info "Reusing source repository in place at ${B2U_INSTALL_DIR}"
elif [[ -d "${B2U_INSTALL_DIR}/.git" ]]; then
  info "Updating repository at ${B2U_INSTALL_DIR}"
  if git -C "$B2U_INSTALL_DIR" remote get-url origin >/dev/null 2>&1; then
    git -C "$B2U_INSTALL_DIR" remote set-url origin "$REPO_URL"
  else
    git -C "$B2U_INSTALL_DIR" remote add origin "$REPO_URL"
  fi
  git -C "$B2U_INSTALL_DIR" fetch --all --tags
  git -C "$B2U_INSTALL_DIR" checkout "$REPO_BRANCH"
  if git -C "$B2U_INSTALL_DIR" symbolic-ref -q HEAD >/dev/null; then
    git -C "$B2U_INSTALL_DIR" pull --ff-only origin "$REPO_BRANCH"
  fi
else
  info "Installing repository into ${B2U_INSTALL_DIR}"
  if [[ -e "$B2U_INSTALL_DIR" ]]; then
    backup_path="${B2U_INSTALL_DIR}.backup.$(timestamp)"
    warn "Moving existing path at ${B2U_INSTALL_DIR} to ${backup_path} before cloning."
    mv "$B2U_INSTALL_DIR" "$backup_path"
  fi
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$B2U_INSTALL_DIR"
fi

[[ -d "$B2U_INSTALL_DIR" ]] || fail "Install directory not found: $B2U_INSTALL_DIR"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
if systemctl is-active --quiet "${B2U_SERVICE_UNIT}" 2>/dev/null; then
  info "Stopping ${B2U_SERVICE_UNIT} before virtual environment recreation"
  systemctl stop "${B2U_SERVICE_UNIT}" || fail "Failed to stop ${B2U_SERVICE_UNIT}"
fi
info "Recreating virtual environment at ${VENV_DIR}"
recreate_venv "$VENV_DIR"
"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install --upgrade "$B2U_INSTALL_DIR"
ok "Virtual environment updated at ${VENV_DIR}"

install_service_unit
write_default_env_file
install_cli_wrapper
systemctl daemon-reload
activate_service_unit
ok "Service ${B2U_SERVICE_UNIT} enabled and started"

if "${VENV_DIR}/bin/python" -m bluetooth_2_usb --version >/dev/null; then
  ok "CLI version check succeeded"
else
  fail "CLI version check failed"
fi

if "${VENV_DIR}/bin/python" -m bluetooth_2_usb --validate-env; then
  ok "Environment validation passed"
else
  warn "Environment validation reports missing runtime prerequisites until after reboot"
fi

cat <<EOF

${BOLD}Next steps${NC}
1. Reboot the Pi so the updated boot configuration takes effect.
2. After reboot, run:
   sudo ${B2U_INSTALL_DIR}/scripts/smoke_test.sh
3. For read-only mode afterwards, choose one of:
   sudo ${B2U_INSTALL_DIR}/scripts/enable_readonly_overlayfs.sh --mode easy
   sudo ${B2U_INSTALL_DIR}/scripts/setup_persistent_bluetooth_state.sh --device /dev/sda1
   sudo ${B2U_INSTALL_DIR}/scripts/enable_readonly_overlayfs.sh --mode persistent
EOF

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

trap - EXIT
