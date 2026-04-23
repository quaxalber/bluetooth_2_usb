#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/paths.sh
source "${SCRIPT_DIR}/lib/paths.sh"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=./lib/bluetooth.sh
source "${SCRIPT_DIR}/lib/bluetooth.sh"
# shellcheck source=./lib/boot.sh
source "${SCRIPT_DIR}/lib/boot.sh"
# shellcheck source=./lib/readonly.sh
source "${SCRIPT_DIR}/lib/readonly.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
VERBOSE=0
EXIT_CODE=0
SOFT_WARNINGS=0
ALLOW_NON_PI="${ALLOW_NON_PI:-0}"
SMOKETEST_POST_REBOOT="${SMOKETEST_POST_REBOOT:-0}"

usage() {
  cat <<EOF
Usage: sudo ./scripts/smoketest.sh [options]
  --verbose           Print detailed diagnostics, including journalctl
  --allow-non-pi      Do not fail when OverlayFS detection is unavailable
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose)
      VERBOSE=1
      shift
      ;;
    --allow-non-pi)
      ALLOW_NON_PI=1
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
prepare_log "smoketest"
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
EXPECTED_OVERLAY_LINE="$(expected_dwc2_overlay_line 2>/dev/null || true)"
OVERLAY_STATUS="$(overlay_status)"
ROOT_OVERLAY_ACTIVE="unknown"
ROOT_FILESYSTEM_TYPE="unknown"
BLUETOOTH_STATE_PERSISTENT="no"
CONFIGURED_INITRAMFS_FILE="$(configured_initramfs_file)"
EXPECTED_BOOT_INITRAMFS_FILE="$(expected_boot_initramfs_file || true)"
EXPECTED_BOOT_INITRAMFS_PATH=""

if ROOT_FILESYSTEM_TYPE="$(current_root_filesystem_type)"; then
  if [[ "$ROOT_FILESYSTEM_TYPE" == "overlay" ]]; then
    ROOT_OVERLAY_ACTIVE="yes"
  else
    ROOT_OVERLAY_ACTIVE="no"
  fi
else
  if [[ "$ALLOW_NON_PI" == "1" ]]; then
    soft_warn "Could not determine the live root filesystem type"
  elif [[ "$OVERLAY_STATUS" == "enabled" && "$SMOKETEST_POST_REBOOT" != "1" ]]; then
    soft_warn "Could not determine the live root filesystem type before reboot"
  else
    warn "Could not determine the live root filesystem type"
    EXIT_CODE=1
  fi
fi

if bluetooth_state_persistent; then
  BLUETOOTH_STATE_PERSISTENT="yes"
fi

if [[ -n "$EXPECTED_BOOT_INITRAMFS_FILE" ]]; then
  EXPECTED_BOOT_INITRAMFS_PATH="$(boot_initramfs_target_path "$EXPECTED_BOOT_INITRAMFS_FILE" 2>/dev/null || true)"
fi

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

print_verbose_section_header() {
  if [[ ${VERBOSE_SECTION_COUNT:-0} -gt 0 ]]; then
    echo
  fi
  VERBOSE_SECTION_COUNT=$((VERBOSE_SECTION_COUNT + 1))
  echo "## $1"
}

if [[ -z "$EXPECTED_OVERLAY_LINE" ]]; then
  if [[ "$ALLOW_NON_PI" == "1" ]]; then
    soft_warn "Could not determine expected Raspberry Pi overlay line"
  else
    warn "Could not determine expected Raspberry Pi overlay line"
    EXIT_CODE=1
  fi
elif grep -qxF "$EXPECTED_OVERLAY_LINE" "$CONFIG_TXT"; then
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

PAIRED_COUNT=0
if PAIRED_COUNT="$(bluetooth_paired_count)"; then
  if [[ "${PAIRED_COUNT:-0}" -gt 0 ]]; then
    ok "Paired Bluetooth devices detected (${PAIRED_COUNT})"
  else
    soft_warn "No paired Bluetooth devices detected"
  fi
else
  warn "bluetoothctl failed while listing paired devices"
  EXIT_CODE=1
fi

if [[ -d /var/lib/bluetooth ]]; then
  ok "Bluetooth state directory exists"
else
  warn "Bluetooth state directory is missing"
  EXIT_CODE=1
fi

case "$OVERLAY_STATUS" in
  enabled)
    ok "OverlayFS boot configuration is enabled"
    ;;
  disabled)
    ok "OverlayFS boot configuration is disabled"
    ;;
  *)
    warn "OverlayFS boot configuration status is unknown"
    if [[ "$ALLOW_NON_PI" != "1" ]]; then
      EXIT_CODE=1
    fi
    ;;
esac

if [[ "$ROOT_OVERLAY_ACTIVE" == "yes" ]]; then
  ok "Root overlay is active"
elif [[ "$ROOT_OVERLAY_ACTIVE" == "unknown" ]]; then
  if [[ "$ALLOW_NON_PI" == "1" ]]; then
    soft_warn "Could not determine whether the root overlay is active"
  elif [[ "$OVERLAY_STATUS" == "enabled" && "$SMOKETEST_POST_REBOOT" != "1" ]]; then
    soft_warn "Could not determine whether the root overlay is active before reboot"
  else
    warn "Could not determine whether the root overlay is active"
    EXIT_CODE=1
  fi
  ROOT_MOUNT_REPORT="$(root_overlay_report)"
  if [[ -n "$ROOT_MOUNT_REPORT" ]]; then
    printf '%s\n' "$ROOT_MOUNT_REPORT"
  fi
elif [[ "$OVERLAY_STATUS" == "enabled" ]]; then
  if [[ "$SMOKETEST_POST_REBOOT" == "1" ]]; then
    warn "Root overlay is not active"
    EXIT_CODE=1
  else
    soft_warn "Root overlay is not active; reboot may still be pending"
  fi
  ROOT_MOUNT_REPORT="$(root_overlay_report)"
  if [[ -n "$ROOT_MOUNT_REPORT" ]]; then
    printf '%s\n' "$ROOT_MOUNT_REPORT"
  fi
else
  ok "Root overlay is inactive"
fi

if [[ "$OVERLAY_STATUS" == "enabled" || "$ROOT_OVERLAY_ACTIVE" == "yes" || "$READONLY_MODE" == "persistent" ]]; then
  if [[ -n "$EXPECTED_BOOT_INITRAMFS_PATH" ]]; then
    if [[ -s "$EXPECTED_BOOT_INITRAMFS_PATH" ]]; then
      ok "Boot initramfs is present (${EXPECTED_BOOT_INITRAMFS_PATH})"
    else
      warn "Boot initramfs is missing or empty (${EXPECTED_BOOT_INITRAMFS_PATH})"
      EXIT_CODE=1
    fi
  else
    warn "Boot initramfs target could not be determined"
    EXIT_CODE=1
  fi
elif [[ -n "$EXPECTED_BOOT_INITRAMFS_PATH" ]]; then
  if [[ -s "$EXPECTED_BOOT_INITRAMFS_PATH" ]]; then
    ok "Boot initramfs is present (${EXPECTED_BOOT_INITRAMFS_PATH})"
  else
    soft_warn "Boot initramfs is not present yet (${EXPECTED_BOOT_INITRAMFS_PATH})"
  fi
fi

if machine_id_valid; then
  if [[ "$READONLY_MODE" == "persistent" ]]; then
    ok "machine-id is ready for persistent read-only mode"
  else
    ok "machine-id is stable"
  fi
elif [[ "$OVERLAY_STATUS" == "enabled" || "$READONLY_MODE" == "persistent" ]]; then
  if [[ "$READONLY_MODE" == "persistent" ]]; then
    warn "machine-id is missing or invalid for persistent read-only mode"
  else
    warn "machine-id is missing or invalid"
  fi
  EXIT_CODE=1
fi

if [[ "$BLUETOOTH_STATE_PERSISTENT" == "yes" ]]; then
  if [[ "$READONLY_MODE" == "persistent" ]]; then
    ok "Bluetooth state is mounted persistently"
  else
    ok "Bluetooth state persistence is active"
  fi
elif [[ "$OVERLAY_STATUS" == "enabled" || "$READONLY_MODE" == "persistent" ]]; then
  if [[ "$READONLY_MODE" == "persistent" ]]; then
    warn "Bluetooth state is not mounted persistently"
  else
    warn "Bluetooth state persistence is not active"
  fi
  EXIT_CODE=1
else
  ok "Bluetooth state persistence is not configured"
fi

if [[ "$READONLY_MODE" == "persistent" ]]; then
  ok "Read-only mode is persistent"
elif [[ "$READONLY_MODE" == "unknown" ]]; then
  warn "Read-only mode could not be determined"
  EXIT_CODE=1
else
  if [[ "$OVERLAY_STATUS" == "disabled" && "$ROOT_OVERLAY_ACTIVE" == "no" ]]; then
    ok "Read-only mode is disabled"
  elif [[ "$OVERLAY_STATUS" == "enabled" && "$ROOT_OVERLAY_ACTIVE" == "no" ]]; then
    warn "Read-only mode is not persistent"
    if [[ "$SMOKETEST_POST_REBOOT" == "1" ]]; then
      EXIT_CODE=1
    fi
  elif [[ "$OVERLAY_STATUS" == "enabled" && "$ROOT_OVERLAY_ACTIVE" == "unknown" ]]; then
    if [[ "$SMOKETEST_POST_REBOOT" == "1" ]]; then
      warn "Read-only mode could not be confirmed after reboot"
      EXIT_CODE=1
    else
      soft_warn "Read-only mode could not be confirmed yet; reboot may still be pending"
    fi
  elif [[ "$OVERLAY_STATUS" == "disabled" && "$ROOT_OVERLAY_ACTIVE" == "yes" ]]; then
    warn "Read-only mode config drift: overlay active but not configured to persist"
    EXIT_CODE=1
  else
    warn "Read-only mode is not persistent"
    EXIT_CODE=1
  fi
fi

if [[ $VERBOSE -eq 1 ]]; then
  VERBOSE_SECTION_COUNT=0
  print_verbose_section_header "Summary"
  echo "Boot config: ${CONFIG_TXT}"
  echo "Cmdline: ${CMDLINE_TXT}"
  echo "modules-load token: ${MODULES_LOAD_VALUE:-<missing>}"
  echo "required modules: $(required_modules_list)"
  echo "required modules status: $(required_modules_status)"
  echo "expected overlay line: ${EXPECTED_OVERLAY_LINE}"
  echo "configured kernel image: $(configured_kernel_image)"
  echo "configured initramfs file: ${CONFIGURED_INITRAMFS_FILE:-<none>}"
  echo "expected boot initramfs file: ${EXPECTED_BOOT_INITRAMFS_FILE:-<none>}"
  echo "expected boot initramfs path: ${EXPECTED_BOOT_INITRAMFS_PATH:-<none>}"
  echo "UDC controllers: ${UDC_LIST:-<none>}"
  echo "UDC state path: ${UDC_STATE_PATH:-<unknown>}"
  echo "UDC state: ${UDC_STATE_VALUE:-<unknown>}"
  echo "Readonly mode: ${READONLY_MODE}"
  echo "OverlayFS configured: ${OVERLAY_STATUS}"
  echo "Allow non-Pi overlay bypass: ${ALLOW_NON_PI}"
  echo "Root filesystem type: ${ROOT_FILESYSTEM_TYPE}"
  echo "Root overlay active: ${ROOT_OVERLAY_ACTIVE}"
  echo "Root mount: $(root_overlay_report)"
  echo "Bluetooth state persistent: ${BLUETOOTH_STATE_PERSISTENT}"
  echo "Smoketest post-reboot mode: ${SMOKETEST_POST_REBOOT}"
  echo "Relayable device count: ${RELAYABLE_COUNT:-unknown}"
  echo "Paired Bluetooth device count: ${PAIRED_COUNT:-unknown}"
  echo "Non-fatal warning count: ${SOFT_WARNINGS}"
  print_verbose_section_header "CLI validate-env output"
  cat "$VALIDATE_LOG"
  print_verbose_section_header "Service config check"
  cat "$SERVICE_CONFIG_LOG"
  print_verbose_section_header "bluetoothctl show"
  cat "$BLUETOOTH_SHOW_LOG"
  print_verbose_section_header "btmgmt info"
  cat "$BTMGMT_INFO_LOG"
  print_verbose_section_header "rfkill bluetooth"
  cat "$RFKILL_LOG"
  print_verbose_section_header "Device inventory"
  cat "$LIST_DEVICES_JSON"
  print_verbose_section_header "Mount details"
  findmnt -n -T / 2>/dev/null || true
  findmnt -n -T /var/lib/bluetooth 2>/dev/null || true
  findmnt -n "$B2U_PERSIST_MOUNT" 2>/dev/null || true
  print_verbose_section_header "Service status"
  systemctl --no-pager --full status "${B2U_SERVICE_UNIT}" || true
  print_verbose_section_header "Journal"
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
