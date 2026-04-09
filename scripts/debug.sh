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
# shellcheck source=./lib/report.sh
source "${SCRIPT_DIR}/lib/report.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
DURATION=""
REPORT_FILE=""
REPORT_BODY=""
OUT=""
SERVICE_WAS_STOPPED=0
STOP_SIGNAL=""
LIVE_DEBUG_STATUS=0
REPORT_STATUS="ok"
SECTION_STATUS="ok"
SECTION_TITLE=""
SECTION_OUT=""

usage() {
  cat <<EOF
Usage: sudo ./scripts/debug.sh [--duration <sec>]
  --duration <sec>    Limit the live Bluetooth-2-USB debug run to <sec>
                      If omitted, the live debug run continues until interrupted
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)
      require_value "$1" "${2:-}"
      DURATION="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
mkdir -p "$B2U_LOG_DIR"
REPORT_FILE="${B2U_LOG_DIR}/debug_$(timestamp).md"
REPORT_BODY="$(mktemp)"
BOOT_DIR="$(detect_boot_dir)"
CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
REDACT_HOSTNAME="${HOSTNAME:-$(hostname)}"
INITIAL_SERVICE_STATE="$(systemctl is-active "${B2U_SERVICE_UNIT}" 2>/dev/null || true)"
load_readonly_config

DEBUG_CMD=""
CONFIG_SUMMARY_JSON=""
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  DEBUG_CMD="$("${VENV_DIR}/bin/python" -m bluetooth_2_usb.service_config --print-shell-command --append-debug 2>/dev/null || true)"
  CONFIG_SUMMARY_JSON="$("${VENV_DIR}/bin/python" -m bluetooth_2_usb.service_config --print-summary-json 2>/dev/null || true)"
fi

note_status() {
  local status="${1:-ok}"

  SECTION_STATUS="$(report_worse_status "$SECTION_STATUS" "$status")"
  REPORT_STATUS="$(report_worse_status "$REPORT_STATUS" "$status")"
}

begin_section() {
  SECTION_TITLE="$1"
  SECTION_STATUS="ok"
  SECTION_OUT="$(mktemp)"
  OUT="$SECTION_OUT"
}

end_section() {
  report_heading "$REPORT_BODY" "##" "$SECTION_STATUS" "$SECTION_TITLE"
  cat "$SECTION_OUT" >>"$REPORT_BODY"
  report_write_line "$REPORT_BODY"
  rm -f "$SECTION_OUT"
  SECTION_OUT=""
  OUT="$REPORT_BODY"
}

timed_command_block() {
  local status="$1"
  local title="$2"
  local timeout_secs="$3"
  local command="$4"
  note_status "$status"
  report_heading "$OUT" "###" "$status" "$title"
  shell_output "$timeout_secs" "$command" | report_code_block >>"$OUT"
  report_write_line "$OUT"
}

section_text_block() {
  local status="$1"
  local title="$2"
  shift 2

  note_status "$status"
  report_text_block "$OUT" "###" "$status" "$title" "$@"
}

redact_stream() {
  perl -pe '
    my $hostname = $ENV{B2U_REDACT_HOSTNAME} // q{};
    if (length $hostname) {
      $hostname =~ s/([^\w:-])/\\$1/g;
      s/\b$hostname\b/<<REDACTED_HOSTNAME>>/g;
    }
    s/PARTUUID=[^\s]+/PARTUUID=<<REDACTED_PARTUUID>>/g;
    s/UUID=[^\s]+/UUID=<<REDACTED_UUID>>/g;
    s/\/dev\/disk\/by-uuid\/[^\s]+/\/dev\/disk\/by-uuid\/<<REDACTED_UUID>>/g;
    s/\/dev\/disk\/by-partuuid\/[^\s]+/\/dev\/disk\/by-partuuid\/<<REDACTED_PARTUUID>>/g;
    s/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/<<REDACTED_UUID>>/gi;
    s/^(?:[0-9a-f]{32})$/<<REDACTED_MACHINE_ID>>/;
    s/\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b/<<REDACTED_BT_MAC>>/g;
  '
}

shell_output() {
  local timeout_secs="$1"
  local command="$2"
  local status=0
  local tmp

  tmp="$(mktemp)"
  B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" timeout "$timeout_secs" bash --noprofile --norc -c "$command" >"$tmp" 2>&1 || status=$?
  B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream <"$tmp" | report_ensure_final_newline
  rm -f "$tmp"
  if [[ $status -eq 124 ]]; then
    printf '[timed out after %ss]\n' "$timeout_secs"
  elif [[ $status -ne 0 ]]; then
    printf '[command exited with status %s]\n' "$status"
  fi
}

cleanup() {
  local exit_code=$?

  trap - EXIT INT TERM

  if [[ $SERVICE_WAS_STOPPED -eq 1 ]]; then
    if ! systemctl start "${B2U_SERVICE_UNIT}"; then
      warn "Failed to restart ${B2U_SERVICE_UNIT} after debug run"
      [[ $exit_code -eq 0 ]] && exit_code=1
    fi
  fi

  if [[ -n "$REPORT_BODY" && -f "$REPORT_BODY" ]]; then
    rm -f "$REPORT_BODY"
  fi
  if [[ -n "$SECTION_OUT" && -f "$SECTION_OUT" ]]; then
    rm -f "$SECTION_OUT"
  fi

  if [[ -n "$REPORT_FILE" && -f "$REPORT_FILE" ]]; then
    ok "Wrote: $REPORT_FILE"
  fi

  if [[ $LIVE_DEBUG_STATUS -ne 0 && $exit_code -eq 0 ]]; then
    exit_code=$LIVE_DEBUG_STATUS
  fi

  if [[ -n "$STOP_SIGNAL" ]]; then
    case "$STOP_SIGNAL" in
      INT) exit 130 ;;
      TERM) exit 143 ;;
    esac
  fi

  exit "$exit_code"
}

trap cleanup EXIT
trap 'STOP_SIGNAL="INT"' INT
trap 'STOP_SIGNAL="TERM"' TERM

stop_service_for_debug() {
  if systemctl is-active --quiet "${B2U_SERVICE_UNIT}"; then
    systemctl stop "${B2U_SERVICE_UNIT}"
    SERVICE_WAS_STOPPED=1
  fi
}

run_live_debug_block() {
  local command="$1"
  local status=0
  local tmp
  local fifo
  local tee_pid=""
  local child_pid=""
  local interrupted=""

  echo '```console' >>"$OUT"
  tmp="$(mktemp)"
  fifo="$(mktemp -u)"
  mkfifo "$fifo"
  tee "$tmp" <"$fifo" &
  tee_pid=$!
  info "Streaming live Bluetooth-2-USB debug output to stdout and $REPORT_FILE"

  if [[ -n "$DURATION" ]]; then
    timeout "$DURATION" bash --noprofile --norc -c "$command" >"$fifo" 2>&1 || status=$?
  else
    trap 'interrupted="INT"; STOP_SIGNAL="INT"; [[ -n "$child_pid" ]] && kill -INT -- "-$child_pid" 2>/dev/null || true' INT
    trap 'interrupted="TERM"; STOP_SIGNAL="TERM"; [[ -n "$child_pid" ]] && kill -TERM -- "-$child_pid" 2>/dev/null || true' TERM
    setsid bash --noprofile --norc -c "$command" >"$fifo" 2>&1 &
    child_pid=$!
    wait "$child_pid" || status=$?
    trap 'STOP_SIGNAL="INT"' INT
    trap 'STOP_SIGNAL="TERM"' TERM
  fi

  wait "$tee_pid" || true
  rm -f "$fifo"

  if [[ -s "$tmp" ]]; then
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream <"$tmp" | report_ensure_final_newline >>"$OUT"
  else
    printf '<no output>\n' >>"$OUT"
  fi

  if [[ $status -eq 124 ]]; then
    printf '[timed out after %ss]\n' "$DURATION" >>"$OUT"
  elif [[ -n "$interrupted" ]]; then
    printf '[interrupted by %s]\n' "$interrupted" >>"$OUT"
  elif [[ $status -ne 0 ]]; then
    printf '[command exited with status %s]\n' "$status" >>"$OUT"
  fi

  echo '```' >>"$OUT"
  rm -f "$tmp"

  if [[ -n "$interrupted" ]]; then
    case "$interrupted" in
      INT) return 130 ;;
      TERM) return 143 ;;
    esac
  fi

  return 0
}

begin_section "System"
timed_command_block "ok" "Kernel" 5 "uname -a"
[[ -f /etc/os-release ]] && timed_command_block "ok" "OS release" 5 "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"
timed_command_block "ok" "Hardware model" 5 "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"
end_section

begin_section "Boot"
section_text_block "ok" "Boot directory" "boot_dir=${BOOT_DIR}"
config_status="ok"
config_command="grep -nE '^\[all\]|dtoverlay=dwc2.*' '$CONFIG_TXT'"
config_fallback="missing: $CONFIG_TXT"
[[ -f "$CONFIG_TXT" ]] || config_status="fail"
if [[ -f "$CONFIG_TXT" ]]; then
  timed_command_block "$config_status" "config.txt dwc2 lines" 5 "$config_command"
else
  section_text_block "$config_status" "config.txt dwc2 lines" "$config_fallback"
fi
cmdline_status="ok"
cmdline_command="cat '$CMDLINE_TXT'"
cmdline_fallback="missing: $CMDLINE_TXT"
[[ -f "$CMDLINE_TXT" ]] || cmdline_status="fail"
if [[ -f "$CMDLINE_TXT" ]]; then
  timed_command_block "$cmdline_status" "cmdline.txt" 5 "$cmdline_command"
else
  section_text_block "$cmdline_status" "cmdline.txt" "$cmdline_fallback"
fi
end_section

begin_section "Runtime prerequisites"
timed_command_block "ok" "Detected UDC controllers" 5 "ls /sys/class/udc 2>/dev/null || true"
if [[ -d /sys/kernel/config/usb_gadget ]]; then
  section_text_block "ok" "configfs gadget path" "/sys/kernel/config/usb_gadget exists"
else
  section_text_block "fail" "configfs gadget path" "configfs missing"
fi
section_text_block "ok" "OverlayFS status" "overlayfs=$(overlay_status)"
readonly_mode_status="ok"
readonly_mode_value="readonly_mode=$(readonly_mode)"
persist_status="ok"
persist_value="bluetooth_state_persistent=no"
if bluetooth_state_persistent 2>/dev/null; then
  persist_status="ok"
  persist_value="bluetooth_state_persistent=yes"
elif [[ "$(overlay_status)" == "enabled" || -f "$B2U_READONLY_ENV_FILE" ]]; then
  persist_status="warn"
fi
section_text_block "$readonly_mode_status" "Read-only mode" "$readonly_mode_value"
section_text_block "$persist_status" "Persistent Bluetooth-state detection" "$persist_value"
if [[ -f "$B2U_READONLY_ENV_FILE" ]]; then
  timed_command_block "ok" "Read-only environment file" 5 "cat '$B2U_READONLY_ENV_FILE'"
fi
timed_command_block "ok" "Overlay and tmpfs mounts" 5 "findmnt -t overlay,tmpfs 2>/dev/null || true"
timed_command_block "ok" "Bluetooth state mount" 5 "findmnt -n -T /var/lib/bluetooth 2>/dev/null || true"
timed_command_block "ok" "Persistent mount target" 5 "findmnt -n '$B2U_PERSIST_MOUNT' 2>/dev/null || true"
machine_id_status="ok"
machine_id_value="machine_id_valid=no"
if machine_id_valid; then
  machine_id_status="ok"
  machine_id_value="machine_id_valid=yes"
fi
section_text_block "$machine_id_status" "machine-id validation" "$machine_id_value"
if [[ -d /var/lib/bluetooth ]]; then
  timed_command_block "ok" "Bluetooth state files" 5 "find /var/lib/bluetooth -type f | sort"
else
  section_text_block "fail" "Bluetooth state files" "/var/lib/bluetooth missing"
fi
end_section

begin_section "systemd"
service_state_status="warn"
service_state_value="service_state_before_debug=${INITIAL_SERVICE_STATE:-unknown}"
service_status_heading="warn"
if [[ "${INITIAL_SERVICE_STATE:-unknown}" == "active" ]]; then
  service_state_status="ok"
  service_state_value="service_state_before_debug=active"
  service_status_heading="ok"
fi
section_text_block "$service_state_status" "Initial service state" "$service_state_value"
timed_command_block "$service_status_heading" "Service status" 8 "systemctl --no-pager --full status '${B2U_SERVICE_UNIT}'"
timed_command_block "ok" "Recent service journal" 8 "journalctl -b -u '${B2U_SERVICE_UNIT}' -n 200 --no-pager"
bluetooth_service_status="ok"
if ! systemctl is-active --quiet bluetooth.service; then
  bluetooth_service_status="warn"
fi
timed_command_block "$bluetooth_service_status" "bluetooth.service status" 8 "systemctl --no-pager --full status bluetooth.service"
end_section

begin_section "dmesg"
timed_command_block "ok" "Relevant kernel log lines" 8 "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"
end_section

begin_section "Bluetooth"
bluetooth_show_status="warn"
if bluetooth_controller_powered; then
  bluetooth_show_status="ok"
fi
timed_command_block "$bluetooth_show_status" "bluetoothctl show" 8 "bluetoothctl show"
paired_status="warn"
if [[ "$(bluetooth_paired_count)" -gt 0 ]]; then
  paired_status="ok"
fi
timed_command_block "$paired_status" "Paired devices" 8 "bluetoothctl devices Paired"
timed_command_block "ok" "btmgmt info" 8 "btmgmt info"
rfkill_status="warn"
if bluetooth_rfkill_entries >/dev/null 2>&1 && ! bluetooth_rfkill_blocked; then
  rfkill_status="ok"
fi
timed_command_block "$rfkill_status" "rfkill bluetooth state" 8 "rfkill list bluetooth 2>/dev/null || true; for type_file in /sys/class/rfkill/rfkill*/type; do [[ -f \"\$type_file\" ]] || continue; [[ \"\$(cat \"\$type_file\" 2>/dev/null || true)\" == \"bluetooth\" ]] || continue; rfkill_dir=\$(dirname \"\$type_file\"); printf '%s type=bluetooth soft=%s hard=%s state=%s\n' \"\$(basename \"\$rfkill_dir\")\" \"\$(cat \"\$rfkill_dir/soft\" 2>/dev/null || printf '?')\" \"\$(cat \"\$rfkill_dir/hard\" 2>/dev/null || printf '?')\" \"\$(cat \"\$rfkill_dir/state\" 2>/dev/null || printf '?')\"; done"
end_section

begin_section "CLI"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  timed_command_block "ok" "CLI version" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --version"
  timed_command_block "ok" "CLI environment validation" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --validate-env"
  timed_command_block "ok" "Service config summary" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb.service_config --print-summary-json"
  timed_command_block "ok" "Device inventory (json)" 8 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --list_devices --output json"

  stop_service_for_debug
  redacted_debug_cmd="$(
    printf '%s\n' "live_debug_command=${DEBUG_CMD}" \
      | B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream
  )"

  section_text_block "ok" "Live debug setup" \
    "service_stopped_for_live_debug=$([[ $SERVICE_WAS_STOPPED -eq 1 ]] && echo yes || echo no)" \
    "$([[ -n "$DURATION" ]] && printf 'live_debug_duration=%ss' "$DURATION" || printf 'live_debug_duration=until interrupted')" \
    "$redacted_debug_cmd"
  note_status "ok"
  report_heading "$OUT" "###" "ok" "Live Bluetooth-2-USB debug output"
  if [[ -n "$DURATION" ]]; then
    info "Live debug duration: ${DURATION}s"
  else
    info "Live debug duration: until interrupted"
  fi
  if [[ -n "$DEBUG_CMD" ]]; then
    if ! run_live_debug_block "${DEBUG_CMD}"; then
      LIVE_DEBUG_STATUS=$?
      SECTION_STATUS="$(report_worse_status "$SECTION_STATUS" "fail")"
      REPORT_STATUS="$(report_worse_status "$REPORT_STATUS" "fail")"
    fi
  else
    section_text_block "fail" "Live debug setup" "Could not build debug command from structured runtime config."
    LIVE_DEBUG_STATUS=1
  fi
else
  section_text_block "fail" "CLI runtime" "missing virtualenv at ${VENV_DIR}"
  LIVE_DEBUG_STATUS=1
fi
end_section

: >"$REPORT_FILE"
report_heading "$REPORT_FILE" "#" "$REPORT_STATUS" "bluetooth_2_usb debug report"
report_write_line "$REPORT_FILE"
report_write_line "$REPORT_FILE" "_Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")_"
report_write_line "$REPORT_FILE"
cat "$REPORT_BODY" >>"$REPORT_FILE"
