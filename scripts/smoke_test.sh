#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

INSTALL_DIR="$B2U_DEFAULT_INSTALL_DIR"
SERVICE_NAME="$B2U_DEFAULT_SERVICE_NAME"
VENV_DIR="${INSTALL_DIR}/venv"
VERBOSE=0
EXIT_CODE=0

usage() {
  cat <<EOF
Usage: sudo ./smoke_test.sh [options]
  --dir <path>        Install directory. Default: ${B2U_DEFAULT_INSTALL_DIR}
  --service <name>    Service name. Default: ${B2U_DEFAULT_SERVICE_NAME}
  --venv <path>       Virtualenv path. Default: ${VENV_DIR}
  --verbose           Print detailed diagnostics, including journalctl
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; VENV_DIR="${INSTALL_DIR}/venv"; shift 2 ;;
    --service) SERVICE_NAME="$2"; shift 2 ;;
    --venv) VENV_DIR="$2"; shift 2 ;;
    --verbose) VERBOSE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "smoke"
load_readonly_config

CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
READONLY_MODE="$(readonly_mode)"
VALIDATE_LOG="$(mktemp)"
DRY_RUN_LOG="$(mktemp)"
trap 'rm -f "$VALIDATE_LOG" "$DRY_RUN_LOG"' EXIT

if grep -qE '^\s*dtoverlay=dwc2' "$CONFIG_TXT"; then
  ok "config.txt contains a dwc2 overlay"
else
  warn "config.txt is missing a dwc2 overlay"
  EXIT_CODE=1
fi

if grep -q 'modules-load=' "$CMDLINE_TXT"; then
  ok "cmdline.txt contains modules-load"
else
  warn "cmdline.txt is missing modules-load"
  EXIT_CODE=1
fi

if [[ -d /sys/kernel/config/usb_gadget ]]; then
  ok "configfs gadget path is present"
else
  warn "configfs gadget path is missing"
  EXIT_CODE=1
fi

if ls /sys/class/udc >/dev/null 2>&1 && [[ -n "$(ls /sys/class/udc 2>/dev/null || true)" ]]; then
  ok "UDC is present"
else
  warn "No UDC detected"
  EXIT_CODE=1
fi

if systemctl is-enabled "${SERVICE_NAME}.service" >/dev/null 2>&1; then
  ok "${SERVICE_NAME}.service is enabled"
else
  warn "${SERVICE_NAME}.service is not enabled"
  EXIT_CODE=1
fi

if systemctl is-active "${SERVICE_NAME}.service" >/dev/null 2>&1; then
  ok "${SERVICE_NAME}.service is active"
else
  warn "${SERVICE_NAME}.service is not active"
  EXIT_CODE=1
fi

if [[ -x "${VENV_DIR}/bin/python" ]]; then
  ok "Virtualenv interpreter is present"
else
  warn "Virtualenv interpreter is missing"
  EXIT_CODE=1
fi

if [[ -x "${VENV_DIR}/bin/python" ]] && "${VENV_DIR}/bin/python" -m bluetooth_2_usb --validate-env >"$VALIDATE_LOG" 2>&1; then
  ok "CLI environment validation passed"
else
  warn "CLI environment validation failed"
  EXIT_CODE=1
fi

if [[ -x "${VENV_DIR}/bin/python" ]] && "${VENV_DIR}/bin/python" -m bluetooth_2_usb --dry-run >"$DRY_RUN_LOG" 2>&1; then
  ok "CLI dry-run passed"
else
  warn "CLI dry-run failed"
  EXIT_CODE=1
fi

if [[ -d /var/lib/bluetooth ]]; then
  ok "Bluetooth state directory exists"
else
  warn "Bluetooth state directory is missing"
  EXIT_CODE=1
fi

if [[ "$READONLY_MODE" == "persistent" ]]; then
  if machine_id_valid; then
    ok "machine-id is stable for persistent read-only mode"
  else
    warn "machine-id is missing or invalid for persistent read-only mode"
    EXIT_CODE=1
  fi

  if bluetooth_state_persistent; then
    ok "Bluetooth state is mounted persistently"
  else
    warn "Bluetooth state is not mounted persistently"
    EXIT_CODE=1
  fi
fi

if [[ $VERBOSE -eq 1 ]]; then
  info "OverlayFS status: $(overlay_status)"
  info "Read-only mode: ${READONLY_MODE}"
  info "Bluetooth state persistent: $(bluetooth_state_persistent && echo yes || echo no)"
  if [[ "$READONLY_MODE" == "easy" ]]; then
    info "Easy read-only mode is best effort only."
  fi
  echo "## CLI validate-env output"
  cat "$VALIDATE_LOG"
  echo "## CLI dry-run output"
  cat "$DRY_RUN_LOG"
  echo "## Mount details"
  findmnt -n -T /var/lib/bluetooth 2>/dev/null || true
  load_readonly_config
  findmnt -n "$B2U_PERSIST_MOUNT" 2>/dev/null || true
  echo "## Service status"
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
  echo "## Journal"
  journalctl -b -u "${SERVICE_NAME}.service" -n 100 --no-pager || true
fi

if [[ $EXIT_CODE -eq 0 ]]; then
  ok "Smoke test PASSED"
else
  fail "Smoke test FAILED"
fi
