#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=./lib/boot.sh
source "${SCRIPT_DIR}/lib/boot.sh"
# shellcheck source=./lib/readonly.sh
source "${SCRIPT_DIR}/lib/readonly.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
VERBOSE=0
EXIT_CODE=0

usage() {
  cat <<EOF
Usage: sudo ./scripts/smoke_test.sh [options]
  --verbose           Print detailed diagnostics, including journalctl
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose)
      VERBOSE=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

ensure_root
prepare_log "smoke"
load_readonly_config

CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
READONLY_MODE="$(readonly_mode)"
VALIDATE_LOG="$(mktemp)"
trap 'rm -f "$VALIDATE_LOG"' EXIT

MODULES_LOAD_VALUE="$(grep -oE 'modules-load=[^ ]+' "$CMDLINE_TXT" 2>/dev/null | head -n1 || true)"
UDC_LIST="$(find /sys/class/udc -mindepth 1 -maxdepth 1 -printf '%f ' 2>/dev/null | sed 's/[[:space:]]*$//' || true)"
DWC2_MODE="$(dwc2_mode)"
IFS=',' read -r -a REQUIRED_MODULES <<<"$(required_boot_modules_csv)"

modules_load_has_required_modules() {
  local module
  local normalized_modules

  normalized_modules=",${MODULES_LOAD_VALUE#modules-load=},"
  for module in "${REQUIRED_MODULES[@]}"; do
    if [[ "$normalized_modules" != *",$module,"* ]]; then
      return 1
    fi
  done
  return 0
}

required_modules_status() {
  local module
  local joined
  local missing_modules=()

  for module in "${REQUIRED_MODULES[@]}"; do
    if [[ ",${MODULES_LOAD_VALUE#modules-load=}," != *",$module,"* ]]; then
      missing_modules+=("$module")
    fi
  done

  if [[ ${#missing_modules[@]} -eq 0 ]]; then
    printf '%s\n' "all present"
  else
    joined="$(printf '%s,' "${missing_modules[@]}")"
    printf '%s\n' "missing: ${joined%,}"
  fi
}

required_modules_list() {
  local joined

  joined="$(printf '%s,' "${REQUIRED_MODULES[@]}")"
  printf '%s\n' "${joined%,}"
}

if grep -qE '^\s*dtoverlay=dwc2' "$CONFIG_TXT"; then
  ok "config.txt contains a dwc2 overlay"
else
  warn "config.txt is missing a dwc2 overlay"
  EXIT_CODE=1
fi

if modules_load_has_required_modules; then
  ok "cmdline.txt contains required modules-load (${MODULES_LOAD_VALUE:-<missing>})"
else
  warn "cmdline.txt is missing required modules ($(required_modules_list)); current value: ${MODULES_LOAD_VALUE:-<missing>}"
  EXIT_CODE=1
fi

if [[ "$DWC2_MODE" == "unknown" ]]; then
  warn "Could not determine whether dwc2 is built-in or modular; boot module validation is heuristic"
fi

if [[ -d /sys/kernel/config/usb_gadget ]]; then
  ok "configfs gadget path is present"
else
  warn "configfs gadget path is missing"
  EXIT_CODE=1
fi

if [[ -n "$UDC_LIST" ]]; then
  ok "UDC is present (${UDC_LIST})"
else
  warn "No UDC detected"
  EXIT_CODE=1
fi

if systemctl is-enabled "${B2U_SERVICE_UNIT}" >/dev/null 2>&1; then
  ok "${B2U_SERVICE_UNIT} is enabled"
else
  warn "${B2U_SERVICE_UNIT} is not enabled"
  EXIT_CODE=1
fi

if systemctl is-active "${B2U_SERVICE_UNIT}" >/dev/null 2>&1; then
  ok "${B2U_SERVICE_UNIT} is active"
else
  warn "${B2U_SERVICE_UNIT} is not active"
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
  sed -n '1,20p' "$VALIDATE_LOG" || true
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

if [[ "$(overlay_status)" == "enabled" && "$READONLY_MODE" != "persistent" ]]; then
  warn "OverlayFS is enabled without persistent Bluetooth state; this setup is unsupported."
  EXIT_CODE=1
fi

info "OverlayFS status: $(overlay_status)"
info "Read-only mode: ${READONLY_MODE}"
info "Bluetooth state persistent: $(bluetooth_state_persistent && echo yes || echo no)"

if [[ $VERBOSE -eq 1 ]]; then
  echo "## Summary"
  echo "Boot config: ${CONFIG_TXT}"
  echo "Cmdline: ${CMDLINE_TXT}"
  echo "modules-load token: ${MODULES_LOAD_VALUE:-<missing>}"
  echo "required modules: $(required_modules_list)"
  echo "required modules status: $(required_modules_status)"
  echo "UDC controllers: ${UDC_LIST:-<none>}"
  echo "Readonly mode: ${READONLY_MODE}"
  echo "OverlayFS: $(overlay_status)"
  echo "Bluetooth state persistent: $(bluetooth_state_persistent && echo yes || echo no)"
  echo "## CLI validate-env output"
  cat "$VALIDATE_LOG"
  echo "## Mount details"
  findmnt -n -T /var/lib/bluetooth 2>/dev/null || true
  findmnt -n "$B2U_PERSIST_MOUNT" 2>/dev/null || true
  echo "## Service status"
  systemctl --no-pager --full status "${B2U_SERVICE_UNIT}" || true
  echo "## Journal"
  journalctl -b -u "${B2U_SERVICE_UNIT}" -n 100 --no-pager || true
fi

if [[ $EXIT_CODE -eq 0 ]]; then
  ok "Smoke test PASSED"
else
  fail "Smoke test FAILED"
fi
