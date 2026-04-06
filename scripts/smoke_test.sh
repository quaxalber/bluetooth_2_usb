#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=./lib/common.sh
source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
VERBOSE=0
MARKDOWN=0
EXIT_CODE=0
OUT=""

usage() {
  cat <<EOF
Usage: sudo ./smoke_test.sh [options]
  --verbose           Print detailed diagnostics, including journalctl
  --markdown          Also write a Markdown report under ${B2U_LOG_DIR}
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose)
      VERBOSE=1
      shift
      ;;
    --markdown)
      MARKDOWN=1
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
prepare_log "smoke"
load_readonly_config

CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
READONLY_MODE="$(readonly_mode)"
VALIDATE_LOG="$(mktemp)"
DRY_RUN_LOG="$(mktemp)"
trap 'rm -f "$VALIDATE_LOG" "$DRY_RUN_LOG"' EXIT

MODULES_LOAD_VALUE="$(grep -oE 'modules-load=[^ ]+' "$CMDLINE_TXT" 2>/dev/null | head -n1 || true)"
UDC_LIST="$(find /sys/class/udc -mindepth 1 -maxdepth 1 -printf '%f ' 2>/dev/null | sed 's/[[:space:]]*$//' || true)"

append_report_line() {
  [[ $MARKDOWN -eq 1 ]] || return 0
  printf '%s\n' "$*" >>"$OUT"
}

append_report_code_block() {
  [[ $MARKDOWN -eq 1 ]] || return 0
  {
    echo '```'
    perl -0pe 's/(?<!\n)\z/\n/'
    echo '```'
  } >>"$OUT"
}

append_report_literal_block() {
  local title="$1"
  shift
  append_report_line "### ${title}"
  printf '%s\n' "$@" | append_report_code_block
  append_report_line
}

append_report_shell_block() {
  local title="$1"
  local command="$2"
  local status=0
  local tmp

  [[ $MARKDOWN -eq 1 ]] || return 0

  append_report_line "### ${title}"
  tmp="$(mktemp)"
  bash -lc "$command" >"$tmp" 2>&1 || status=$?
  cat "$tmp" | append_report_code_block
  rm -f "$tmp"
  if [[ $status -ne 0 ]]; then
    append_report_line "_Command exited with status ${status}_"
    append_report_line
  fi
}

write_markdown_report() {
  local result="PASSED"
  local validate_status="passed"
  local dry_run_status="passed"

  [[ $MARKDOWN -eq 1 ]] || return 0
  [[ $EXIT_CODE -eq 0 ]] || result="FAILED"
  [[ -s "$VALIDATE_LOG" ]] || validate_status="produced no output"
  [[ -s "$DRY_RUN_LOG" ]] || dry_run_status="produced no output"

  append_report_line "# bluetooth_2_usb smoke test report"
  append_report_line
  append_report_line "_Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")_"
  append_report_line

  append_report_line "## Summary"
  append_report_literal_block \
    "Overall result" \
    "smoke_test=${result}" \
    "overlayfs=$(overlay_status)" \
    "readonly_mode=${READONLY_MODE}" \
    "bluetooth_state_persistent=$(bluetooth_state_persistent && echo yes || echo no)"
  append_report_literal_block \
    "Boot and runtime summary" \
    "boot_config=${CONFIG_TXT}" \
    "cmdline=${CMDLINE_TXT}" \
    "modules_load=${MODULES_LOAD_VALUE:-<missing>}" \
    "udc_controllers=${UDC_LIST:-<none>}" \
    "service_unit=${B2U_SERVICE_UNIT}" \
    "venv_python=${VENV_DIR}/bin/python"

  append_report_line "## Checks"
  append_report_literal_block \
    "Boot configuration checks" \
    "dwc2_overlay=$(grep -qE '^\s*dtoverlay=dwc2' "$CONFIG_TXT" && echo yes || echo no)" \
    "modules_load_present=$(grep -q 'modules-load=' "$CMDLINE_TXT" && echo yes || echo no)" \
    "configfs_gadget_path=$([[ -d /sys/kernel/config/usb_gadget ]] && echo present || echo missing)" \
    "udc_present=$([[ -n "$UDC_LIST" ]] && echo yes || echo no)"
  append_report_literal_block \
    "Service and runtime checks" \
    "service_enabled=$(systemctl is-enabled "${B2U_SERVICE_UNIT}" >/dev/null 2>&1 && echo yes || echo no)" \
    "service_active=$(systemctl is-active "${B2U_SERVICE_UNIT}" >/dev/null 2>&1 && echo yes || echo no)" \
    "venv_python_present=$([[ -x "${VENV_DIR}/bin/python" ]] && echo yes || echo no)" \
    "bluetooth_state_dir=$([[ -d /var/lib/bluetooth ]] && echo present || echo missing)"

  append_report_line "## CLI diagnostics"
  append_report_literal_block "CLI environment validation status" "validate_env=${validate_status}"
  cat "$VALIDATE_LOG" | append_report_code_block
  append_report_line
  append_report_literal_block "CLI dry-run status" "dry_run=${dry_run_status}"
  cat "$DRY_RUN_LOG" | append_report_code_block
  append_report_line

  append_report_line "## Mounts and service details"
  append_report_shell_block "Bluetooth state mount" "findmnt -n -T /var/lib/bluetooth 2>/dev/null || true"
  append_report_shell_block "Persistent mount target" "findmnt -n '${B2U_PERSIST_MOUNT}' 2>/dev/null || true"
  append_report_shell_block "Service status" "systemctl --no-pager --full status '${B2U_SERVICE_UNIT}' || true"
  append_report_shell_block "Recent service journal" "journalctl -b -u '${B2U_SERVICE_UNIT}' -n 100 --no-pager || true"
}

if [[ $MARKDOWN -eq 1 ]]; then
  OUT="${B2U_LOG_DIR}/smoke_test_$(timestamp).md"
fi

if grep -qE '^\s*dtoverlay=dwc2' "$CONFIG_TXT"; then
  ok "config.txt contains a dwc2 overlay"
else
  warn "config.txt is missing a dwc2 overlay"
  EXIT_CODE=1
fi

if grep -q 'modules-load=' "$CMDLINE_TXT"; then
  ok "cmdline.txt contains modules-load (${MODULES_LOAD_VALUE})"
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

if [[ -x "${VENV_DIR}/bin/python" ]] && "${VENV_DIR}/bin/python" -m bluetooth_2_usb --dry-run >"$DRY_RUN_LOG" 2>&1; then
  ok "CLI dry-run passed"
else
  warn "CLI dry-run failed"
  sed -n '1,20p' "$DRY_RUN_LOG" || true
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

info "OverlayFS status: $(overlay_status)"
info "Read-only mode: ${READONLY_MODE}"
info "Bluetooth state persistent: $(bluetooth_state_persistent && echo yes || echo no)"

if [[ $VERBOSE -eq 1 ]]; then
  if [[ "$READONLY_MODE" == "easy" ]]; then
    info "Easy read-only mode is best effort only."
  fi
  echo "## Summary"
  echo "Boot config: ${CONFIG_TXT}"
  echo "Cmdline: ${CMDLINE_TXT}"
  echo "modules-load token: ${MODULES_LOAD_VALUE:-<missing>}"
  echo "UDC controllers: ${UDC_LIST:-<none>}"
  echo "Readonly mode: ${READONLY_MODE}"
  echo "OverlayFS: $(overlay_status)"
  echo "Bluetooth state persistent: $(bluetooth_state_persistent && echo yes || echo no)"
  echo "## CLI validate-env output"
  cat "$VALIDATE_LOG"
  echo "## CLI dry-run output"
  cat "$DRY_RUN_LOG"
  echo "## Mount details"
  findmnt -n -T /var/lib/bluetooth 2>/dev/null || true
  findmnt -n "$B2U_PERSIST_MOUNT" 2>/dev/null || true
  echo "## Service status"
  systemctl --no-pager --full status "${B2U_SERVICE_UNIT}" || true
  echo "## Journal"
  journalctl -b -u "${B2U_SERVICE_UNIT}" -n 100 --no-pager || true
fi

write_markdown_report
if [[ $MARKDOWN -eq 1 ]]; then
  ok "Wrote: ${OUT}"
fi

if [[ $EXIT_CODE -eq 0 ]]; then
  ok "Smoke test PASSED"
else
  fail "Smoke test FAILED"
fi
