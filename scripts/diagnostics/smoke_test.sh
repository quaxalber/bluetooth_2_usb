#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../lib/paths.sh
source "${SCRIPTS_DIR}/lib/paths.sh"
# shellcheck source=../lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"
# shellcheck source=../lib/bluetooth.sh
source "${SCRIPTS_DIR}/lib/bluetooth.sh"
# shellcheck source=../lib/boot.sh
source "${SCRIPTS_DIR}/lib/boot.sh"
# shellcheck source=../lib/readonly.sh
source "${SCRIPTS_DIR}/lib/readonly.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
VERBOSE=0
EXIT_CODE=0
SOFT_WARNINGS=0

usage() {
  cat <<EOF
Usage: sudo ./scripts/diagnostics/smoke_test.sh [options]
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

soft_warn() {
  warn "$1"
  SOFT_WARNINGS=$((SOFT_WARNINGS + 1))
}

CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
READONLY_MODE="$(readonly_mode)"
VALIDATE_LOG="$(mktemp)"
LIST_DEVICES_JSON="$(mktemp)"
BLUETOOTH_SHOW_LOG="$(mktemp)"
BTMGMT_INFO_LOG="$(mktemp)"
SERVICE_CONFIG_LOG="$(mktemp)"
RFKILL_LOG="$(mktemp)"
trap 'rm -f "$VALIDATE_LOG" "$LIST_DEVICES_JSON" "$BLUETOOTH_SHOW_LOG" "$BTMGMT_INFO_LOG" "$SERVICE_CONFIG_LOG" "$RFKILL_LOG"' EXIT

MODULES_LOAD_VALUE="$(grep -oE 'modules-load=[^ ]+' "$CMDLINE_TXT" 2>/dev/null | head -n1 || true)"
UDC_LIST="$(find /sys/class/udc -mindepth 1 -maxdepth 1 -printf '%f ' 2>/dev/null | sed 's/[[:space:]]*$//' || true)"
UDC_STATE_PATH=""
UDC_STATE_VALUE=""
DWC2_MODE="$(dwc2_mode)"
IFS=',' read -r -a REQUIRED_MODULES <<<"$(required_boot_modules_csv)"
EXPECTED_OVERLAY_LINE="$(expected_dwc2_overlay_line)"

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

if grep -qxF "$EXPECTED_OVERLAY_LINE" "$CONFIG_TXT"; then
  ok "config.txt contains expected overlay (${EXPECTED_OVERLAY_LINE})"
else
  warn "config.txt is missing expected overlay (${EXPECTED_OVERLAY_LINE})"
  EXIT_CODE=1
fi

if modules_load_has_required_modules; then
  ok "cmdline.txt contains required modules-load (${MODULES_LOAD_VALUE:-<missing>})"
else
  warn "cmdline.txt is missing required modules ($(required_modules_list)); current value: ${MODULES_LOAD_VALUE:-<missing>}"
  EXIT_CODE=1
fi

if [[ "$DWC2_MODE" == "unknown" ]]; then
  soft_warn "Could not determine whether dwc2 is built-in or modular; boot module validation is heuristic"
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

if [[ -x "${VENV_DIR}/bin/python" ]]; then
  UDC_STATE_PATH="$(
    "${VENV_DIR}/bin/python" - <<'PY'
from bluetooth_2_usb.cli import get_udc_path

path = get_udc_path()
print(path if path else "")
PY
  )"
fi

if [[ -n "$UDC_STATE_PATH" && -f "$UDC_STATE_PATH" ]]; then
  UDC_STATE_VALUE="$(tr -d '[:space:]' <"$UDC_STATE_PATH" 2>/dev/null || true)"
  if [[ "$UDC_STATE_VALUE" == "configured" ]]; then
    ok "UDC state is configured"
  else
    soft_warn "UDC state is ${UDC_STATE_VALUE:-unknown}"
  fi
fi

if [[ -x "${VENV_DIR}/bin/python" ]] && "${VENV_DIR}/bin/python" -m bluetooth_2_usb.service_config --check >"$SERVICE_CONFIG_LOG" 2>&1; then
  ok "Runtime config is valid"
else
  warn "Runtime config validation failed"
  sed -n '1,20p' "$SERVICE_CONFIG_LOG" || true
  EXIT_CODE=1
fi

if systemctl is-active bluetooth.service >/dev/null 2>&1; then
  ok "bluetooth.service is active"
else
  warn "bluetooth.service is not active"
  EXIT_CODE=1
fi

if bluetoothctl_show >"$BLUETOOTH_SHOW_LOG" 2>&1; then
  if bluetooth_controller_powered_from_file "$BLUETOOTH_SHOW_LOG"; then
    ok "Bluetooth controller is powered"
  else
    warn "Bluetooth controller is visible but not powered"
    EXIT_CODE=1
  fi
else
  warn "bluetoothctl show failed"
  sed -n '1,20p' "$BLUETOOTH_SHOW_LOG" || true
  EXIT_CODE=1
fi

if btmgmt_info >"$BTMGMT_INFO_LOG" 2>&1; then
  ok "btmgmt info succeeded"
else
  warn "btmgmt info failed"
  sed -n '1,20p' "$BTMGMT_INFO_LOG" || true
  EXIT_CODE=1
fi

if bluetooth_rfkill_entries >"$RFKILL_LOG" 2>&1; then
  if bluetooth_rfkill_blocked; then
    warn "Bluetooth rfkill is blocking the controller"
    cat "$RFKILL_LOG"
    EXIT_CODE=1
  else
    ok "Bluetooth rfkill state is not blocked"
  fi
else
  soft_warn "No bluetooth rfkill entries found"
fi

RELAYABLE_COUNT=""
if [[ -x "${VENV_DIR}/bin/python" ]] && "${VENV_DIR}/bin/python" -m bluetooth_2_usb --list_devices --output json >"$LIST_DEVICES_JSON" 2>&1; then
  if RELAYABLE_COUNT="$(
    "${VENV_DIR}/bin/python" - "$LIST_DEVICES_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    devices = json.load(handle)
print(sum(1 for device in devices if device.get("relay_candidate")))
PY
  )"; then
    if [[ "${RELAYABLE_COUNT:-0}" -gt 0 ]]; then
      ok "Relayable input devices detected (${RELAYABLE_COUNT})"
    else
      soft_warn "No relayable input devices detected"
    fi
  else
    RELAYABLE_COUNT=0
    warn "Failed to parse relayable device inventory from ${LIST_DEVICES_JSON}"
    sed -n '1,40p' "$LIST_DEVICES_JSON" || true
    EXIT_CODE=1
  fi
else
  warn "Device inventory failed"
  sed -n '1,40p' "$LIST_DEVICES_JSON" || true
  EXIT_CODE=1
fi

PAIRED_COUNT="$(bluetooth_paired_count)"
if [[ "${PAIRED_COUNT:-0}" -gt 0 ]]; then
  ok "Paired Bluetooth devices detected (${PAIRED_COUNT})"
else
  soft_warn "No paired Bluetooth devices detected"
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
  echo "expected overlay line: ${EXPECTED_OVERLAY_LINE}"
  echo "UDC controllers: ${UDC_LIST:-<none>}"
  echo "UDC state path: ${UDC_STATE_PATH:-<unknown>}"
  echo "UDC state: ${UDC_STATE_VALUE:-<unknown>}"
  echo "Readonly mode: ${READONLY_MODE}"
  echo "OverlayFS: $(overlay_status)"
  echo "Bluetooth state persistent: $(bluetooth_state_persistent && echo yes || echo no)"
  echo "Relayable device count: ${RELAYABLE_COUNT:-unknown}"
  echo "Paired Bluetooth device count: ${PAIRED_COUNT:-unknown}"
  echo "Non-fatal warning count: ${SOFT_WARNINGS}"
  echo "## CLI validate-env output"
  cat "$VALIDATE_LOG"
  echo "## Service config check"
  cat "$SERVICE_CONFIG_LOG"
  echo "## bluetoothctl show"
  cat "$BLUETOOTH_SHOW_LOG"
  echo "## btmgmt info"
  cat "$BTMGMT_INFO_LOG"
  echo "## rfkill bluetooth"
  cat "$RFKILL_LOG"
  echo "## Device inventory"
  cat "$LIST_DEVICES_JSON"
  echo "## Mount details"
  findmnt -n -T /var/lib/bluetooth 2>/dev/null || true
  findmnt -n "$B2U_PERSIST_MOUNT" 2>/dev/null || true
  echo "## Service status"
  systemctl --no-pager --full status "${B2U_SERVICE_UNIT}" || true
  echo "## Journal"
  journalctl -b -u "${B2U_SERVICE_UNIT}" -n 100 --no-pager || true
fi

if [[ $EXIT_CODE -eq 0 ]]; then
  if [[ $SOFT_WARNINGS -gt 0 ]]; then
    ok "Smoke test PASSED (with warnings)"
  else
    ok "Smoke test PASSED"
  fi
else
  fail "Smoke test FAILED"
fi
