#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

INSTALL_DIR="$B2U_DEFAULT_INSTALL_DIR"
SERVICE_NAME="$B2U_DEFAULT_SERVICE_NAME"
REPO_URL="$(default_repo_url)"
REPO_BRANCH="$(default_repo_branch)"
NO_REBOOT=0
SKIP_CLONE=0

usage() {
  cat <<EOF
Usage: sudo ./install.sh [options]
  --repo <url|path>   Repository source. Default: current repo checkout
  --branch <name>     Branch/tag to install. Default: current branch
  --dir <path>        Install directory. Default: ${B2U_DEFAULT_INSTALL_DIR}
  --skip-clone        Reuse existing install directory content
  --no-reboot         Do not prompt for reboot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO_URL="$2"; shift 2 ;;
    --branch) REPO_BRANCH="$2"; shift 2 ;;
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --skip-clone) SKIP_CLONE=1; shift ;;
    --no-reboot) NO_REBOOT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "install"
require_commands apt-get awk grep install python3 sed systemctl

BOOT_DIR="$(detect_boot_dir)"
CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
DWC2_MODE="$(dwc2_mode)"
OVERLAY_LINE="$(board_overlay_line "$MODEL")"

info "Detected model: ${MODEL:-unknown}"
info "Using boot directory: ${BOOT_DIR}"
info "Detected dwc2 mode: ${DWC2_MODE}"

backup_file "$CONFIG_TXT"
backup_file "$CMDLINE_TXT"
normalize_dwc2_overlay "$CONFIG_TXT" "$OVERLAY_LINE"

MODULES="libcomposite"
if [[ "$DWC2_MODE" == "module" ]]; then
  MODULES="dwc2,libcomposite"
fi
normalize_modules_load "$CMDLINE_TXT" "$MODULES"
ok "Boot configuration updated"

apt-get update -y
apt-get install -y --no-install-recommends git python3 python3-pip python3-venv python3-dev
require_commands git

if [[ $SKIP_CLONE -eq 0 ]]; then
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if [[ "$REPO_URL" == "$INSTALL_DIR" ]]; then
    info "Reusing source repository in place at ${INSTALL_DIR}"
  elif [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Updating repository at ${INSTALL_DIR}"
    if git -C "$INSTALL_DIR" remote get-url origin >/dev/null 2>&1; then
      git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
    else
      git -C "$INSTALL_DIR" remote add origin "$REPO_URL"
    fi
    git -C "$INSTALL_DIR" fetch --all --tags
    git -C "$INSTALL_DIR" checkout "$REPO_BRANCH"
    if git -C "$INSTALL_DIR" symbolic-ref -q HEAD >/dev/null; then
      git -C "$INSTALL_DIR" pull --ff-only origin "$REPO_BRANCH"
    fi
  else
    info "Installing repository into ${INSTALL_DIR}"
    rm -rf "$INSTALL_DIR"
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR"
  fi
fi

[[ -d "$INSTALL_DIR" ]] || fail "Install directory not found: $INSTALL_DIR"

VENV_DIR="${INSTALL_DIR}/venv"
info "Recreating virtual environment at ${VENV_DIR}"
recreate_venv "$VENV_DIR"
"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install --upgrade "$INSTALL_DIR"
ok "Virtual environment updated at ${VENV_DIR}"

install_service_unit "$INSTALL_DIR" "$SERVICE_NAME"
write_default_env_file
install_cli_wrapper "$INSTALL_DIR"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"
ok "Service ${SERVICE_NAME}.service enabled and started"

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
   sudo ${INSTALL_DIR}/scripts/smoke_test.sh --verbose
3. For read-only mode afterwards, choose one of:
   sudo ${INSTALL_DIR}/scripts/enable_readonly_overlayfs.sh --mode easy
   sudo ${INSTALL_DIR}/scripts/setup_persistent_bluetooth_state.sh --device /dev/your-device
   sudo ${INSTALL_DIR}/scripts/enable_readonly_overlayfs.sh --mode persistent
EOF

if [[ $NO_REBOOT -eq 0 ]]; then
  read -r -p "Reboot now? [y/N] " answer
  if [[ "${answer,,}" == "y" ]]; then
    sync
    reboot
  fi
fi
