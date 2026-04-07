#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=./lib/common.sh
source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"
# shellcheck source=./lib/report.sh
source "$(cd -- "$(dirname "$0")" && pwd)/lib/report.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
DURATION=""
REDACT=0
OUT=""
SERVICE_WAS_STOPPED=0
STOP_SIGNAL=""
PARSE_ERROR=0
RUN_ARGS="--auto_discover --grab_devices --interrupt_shortcut CTRL+SHIFT+F12"

usage() {
  cat <<EOF
Usage: sudo ./debug.sh [options]
  --duration <sec>    Limit the live Bluetooth-2-USB debug run to <sec>
                      If omitted, the live debug run continues until interrupted
  --redact            Redact host identifiers before writing the report
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)
      require_value "$1" "${2:-}"
      DURATION="$2"
      shift 2
      ;;
    --redact)
      REDACT=1
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
mkdir -p "$B2U_LOG_DIR"
OUT="${B2U_LOG_DIR}/debug_$(timestamp).md"
BOOT_DIR="$(detect_boot_dir)"
CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
REDACT_HOSTNAME="${HOSTNAME:-$(hostname)}"
INITIAL_SERVICE_STATE="$(systemctl is-active "${B2U_SERVICE_UNIT}" 2>/dev/null || true)"
if [[ -f "$B2U_ENV_FILE" ]] && [[ -s "$B2U_ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^BLUETOOTH_2_USB_ARGS=\"([^\"]*)\"$ ]]; then
      RUN_ARGS="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ ^BLUETOOTH_2_USB_ARGS=(.+)$ ]]; then
      RUN_ARGS="${BASH_REMATCH[1]}"
    fi
  done <"$B2U_ENV_FILE"
fi
if [[ -x "${VENV_DIR}/bin/bluetooth_2_usb" ]]; then
  DEBUG_CMD="'${VENV_DIR}/bin/bluetooth_2_usb' ${RUN_ARGS} --debug"
elif [[ -x "${VENV_DIR}/bin/python" ]]; then
  DEBUG_CMD="'${VENV_DIR}/bin/python' -m bluetooth_2_usb ${RUN_ARGS} --debug"
else
  DEBUG_CMD=""
fi

# Load readonly config with error handling to prevent malformed files from aborting report generation
if [ -f "$B2U_READONLY_ENV_FILE" ] && [ -s "$B2U_READONLY_ENV_FILE" ]; then
  # Parse config manually to handle errors gracefully
  B2U_PERSIST_MOUNT="$B2U_PERSIST_MOUNT_PATH"

  PARSE_ERROR=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "$line" ]] || continue
    if [[ ! "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=\"([^\"]*)\"$ ]]; then
      warn "Malformed $B2U_READONLY_ENV_FILE, skipping readonly entries"
      PARSE_ERROR=1
      break
    fi
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      B2U_PERSIST_MOUNT)
        printf -v "$key" '%s' "$value"
        ;;
      B2U_READONLY_MODE | B2U_PERSIST_BLUETOOTH_DIR | B2U_PERSIST_SPEC | B2U_PERSIST_DEVICE)
        :
        ;;
      *)
        warn "Malformed $B2U_READONLY_ENV_FILE, skipping readonly entries"
        PARSE_ERROR=1
        break
        ;;
    esac
  done <"$B2U_READONLY_ENV_FILE"
else
  # Set defaults if file doesn't exist
  B2U_PERSIST_MOUNT="$B2U_PERSIST_MOUNT_PATH"
fi

timed_command_block() {
  local status="$1"
  local title="$2"
  local timeout_secs="$3"
  local command="$4"
  report_heading "$OUT" "###" "$status" "$title"
  shell_output "$timeout_secs" "$command" | report_code_block >>"$OUT"
  report_write_line "$OUT"
}

redact_stream() {
  if [[ $REDACT -ne 1 ]]; then
    cat
    return
  fi

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

  if [[ -n "$OUT" && -f "$OUT" ]]; then
    ok "Wrote: $OUT"
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
  local child_pid=""
  local interrupted=""

  echo '```console' >>"$OUT"
  tmp="$(mktemp)"
  info "Streaming live Bluetooth-2-USB debug output to stdout and $OUT"

  if [[ -n "$DURATION" ]]; then
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" timeout "$DURATION" bash --noprofile --norc -c "$command" \
      > >(B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream | tee "$tmp") 2>&1 || status=$?
  else
    trap 'interrupted="INT"; STOP_SIGNAL="INT"; [[ -n "$child_pid" ]] && kill -INT -- "-$child_pid" 2>/dev/null || true' INT
    trap 'interrupted="TERM"; STOP_SIGNAL="TERM"; [[ -n "$child_pid" ]] && kill -TERM -- "-$child_pid" 2>/dev/null || true' TERM
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" setsid bash --noprofile --norc -c "$command" \
      > >(B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream | tee "$tmp") 2>&1 &
    child_pid=$!
    wait "$child_pid" || status=$?
    trap 'STOP_SIGNAL="INT"' INT
    trap 'STOP_SIGNAL="TERM"' TERM
  fi

  report_ensure_final_newline <"$tmp" >>"$OUT"
  rm -f "$tmp"

  if [[ $status -eq 124 ]]; then
    printf '[timed out after %ss]\n' "$DURATION" >>"$OUT"
  elif [[ -n "$interrupted" ]]; then
    printf '[interrupted by %s]\n' "$interrupted" >>"$OUT"
  elif [[ $status -ne 0 ]]; then
    printf '[command exited with status %s]\n' "$status" >>"$OUT"
  fi

  echo '```' >>"$OUT"

  if [[ -n "$interrupted" ]]; then
    case "$interrupted" in
      INT) return 130 ;;
      TERM) return 143 ;;
    esac
  fi

  return 0
}

report_heading "$OUT" "#" "none" "bluetooth_2_usb debug report"
report_write_line "$OUT"
report_write_line "$OUT" "_Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")_"
report_write_line "$OUT"

report_heading "$OUT" "##" "info" "System"
report_text_block "$OUT" "###" "info" "Hostname" "$(
  printf '%s\n' "$REDACT_HOSTNAME" | B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream
)"
timed_command_block "info" "Kernel" 5 "uname -a"
[[ -f /etc/os-release ]] && timed_command_block "info" "OS release" 5 "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"
timed_command_block "info" "Hardware model" 5 "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"

report_heading "$OUT" "##" "info" "Boot"
report_text_block "$OUT" "###" "info" "Boot directory" "boot_dir=${BOOT_DIR}"
config_status="info"
config_command="grep -nE '^\[all\]|dtoverlay=dwc2.*' '$CONFIG_TXT'"
config_fallback="missing: $CONFIG_TXT"
[[ -f "$CONFIG_TXT" ]] || config_status="fail"
if [[ -f "$CONFIG_TXT" ]]; then
  timed_command_block "$config_status" "config.txt dwc2 lines" 5 "$config_command"
else
  report_text_block "$OUT" "###" "$config_status" "config.txt dwc2 lines" "$config_fallback"
fi
cmdline_status="info"
cmdline_command="cat '$CMDLINE_TXT'"
cmdline_fallback="missing: $CMDLINE_TXT"
[[ -f "$CMDLINE_TXT" ]] || cmdline_status="fail"
if [[ -f "$CMDLINE_TXT" ]]; then
  timed_command_block "$cmdline_status" "cmdline.txt" 5 "$cmdline_command"
else
  report_text_block "$OUT" "###" "$cmdline_status" "cmdline.txt" "$cmdline_fallback"
fi

report_heading "$OUT" "##" "info" "Runtime prerequisites"
timed_command_block "info" "Detected UDC controllers" 5 "ls /sys/class/udc 2>/dev/null || true"
if [[ -d /sys/kernel/config/usb_gadget ]]; then
  report_text_block "$OUT" "###" "ok" "configfs gadget path" "/sys/kernel/config/usb_gadget exists"
else
  report_text_block "$OUT" "###" "fail" "configfs gadget path" "configfs missing"
fi
report_text_block "$OUT" "###" "info" "OverlayFS status" "overlayfs=$(overlay_status)"
readonly_mode_status="info"
readonly_mode_value="readonly_mode=$(readonly_mode 2>/dev/null || echo '<error>')"
persist_status="info"
persist_value="bluetooth_state_persistent=no"
if [ -f "$B2U_READONLY_ENV_FILE" ] && [ -s "$B2U_READONLY_ENV_FILE" ] && [ "$PARSE_ERROR" -eq 1 ]; then
  readonly_mode_status="fail"
  readonly_mode_value="readonly_mode=<config parse error>"
  persist_status="fail"
  persist_value="bluetooth_state_persistent=<config parse error>"
else
  if bluetooth_state_persistent 2>/dev/null; then
    persist_status="ok"
    persist_value="bluetooth_state_persistent=yes"
  fi
fi
report_text_block "$OUT" "###" "$readonly_mode_status" "Read-only mode" "$readonly_mode_value"
report_text_block "$OUT" "###" "$persist_status" "Persistent Bluetooth-state detection" "$persist_value"
if [[ -f "$B2U_READONLY_ENV_FILE" ]]; then
  timed_command_block "info" "Read-only environment file" 5 "cat '$B2U_READONLY_ENV_FILE'"
fi
timed_command_block "info" "Overlay and tmpfs mounts" 5 "findmnt -t overlay,tmpfs 2>/dev/null || true"
timed_command_block "info" "Bluetooth state mount" 5 "findmnt -n -T /var/lib/bluetooth 2>/dev/null || true"
timed_command_block "info" "Persistent mount target" 5 "findmnt -n '$B2U_PERSIST_MOUNT' 2>/dev/null || true"
if [[ -f /etc/machine-id ]]; then
  timed_command_block "info" "machine-id" 5 "cat /etc/machine-id"
fi
machine_id_status="info"
machine_id_value="machine_id_valid=no"
if machine_id_valid; then
  machine_id_status="ok"
  machine_id_value="machine_id_valid=yes"
fi
report_text_block "$OUT" "###" "$machine_id_status" "machine-id validation" "$machine_id_value"
if [[ -d /var/lib/bluetooth ]]; then
  timed_command_block "ok" "Bluetooth state files" 5 "find /var/lib/bluetooth -type f | sort"
else
  report_text_block "$OUT" "###" "fail" "Bluetooth state files" "/var/lib/bluetooth missing"
fi

report_heading "$OUT" "##" "info" "systemd"
service_state_status="warn"
service_state_value="service_state_before_debug=${INITIAL_SERVICE_STATE:-unknown}"
service_status_heading="warn"
if [[ "${INITIAL_SERVICE_STATE:-unknown}" == "active" ]]; then
  service_state_status="ok"
  service_state_value="service_state_before_debug=active"
  service_status_heading="ok"
fi
report_text_block "$OUT" "###" "$service_state_status" "Initial service state" "$service_state_value"
timed_command_block "$service_status_heading" "Service status" 8 "systemctl --no-pager --full status '${B2U_SERVICE_UNIT}'"
timed_command_block "info" "Recent service journal" 8 "journalctl -b -u '${B2U_SERVICE_UNIT}' -n 200 --no-pager"

report_heading "$OUT" "##" "info" "dmesg"
timed_command_block "info" "Relevant kernel log lines" 8 "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"

report_heading "$OUT" "##" "info" "CLI"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  timed_command_block "ok" "CLI version" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --version"
  timed_command_block "ok" "CLI environment validation" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --validate-env"

  stop_service_for_debug

  report_text_block "$OUT" "###" "info" "Live debug setup" \
    "service_stopped_for_live_debug=$([[ $SERVICE_WAS_STOPPED -eq 1 ]] && echo yes || echo no)" \
    "$([[ -n "$DURATION" ]] && printf 'live_debug_duration=%ss' "$DURATION" || printf 'live_debug_duration=until interrupted')" \
    "live_debug_command=${DEBUG_CMD}"
  report_heading "$OUT" "###" "ok" "Live Bluetooth-2-USB debug output"
  if [[ -n "$DURATION" ]]; then
    info "Live debug duration: ${DURATION}s"
  else
    info "Live debug duration: until interrupted"
  fi
  run_live_debug_block "${DEBUG_CMD}"
else
  report_text_block "$OUT" "###" "fail" "CLI runtime" "missing virtualenv at ${VENV_DIR}"
fi
