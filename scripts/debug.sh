#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
DURATION=""
REDACT=0
OUT=""
SERVICE_STOPPED_FOR_DEBUG=0
INTERRUPTED_BY_SIGNAL=""
PARSE_ERROR=0

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
    --duration) require_value "$1" "${2:-}"; DURATION="$2"; shift 2 ;;
    --redact) REDACT=1; shift ;;
    -h|--help) usage; exit 0 ;;
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
SERVICE_INITIAL_STATE="$(systemctl is-active "${B2U_SERVICE_UNIT}" 2>/dev/null || true)"
if [[ -x "${VENV_DIR}/bin/bluetooth_2_usb" ]]; then
  B2U_DEBUG_CMD="'${VENV_DIR}/bin/bluetooth_2_usb' --debug"
elif [[ -x "${VENV_DIR}/bin/python" ]]; then
  B2U_DEBUG_CMD="'${VENV_DIR}/bin/python' -m bluetooth_2_usb --debug"
else
  B2U_DEBUG_CMD=""
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
      B2U_READONLY_MODE|B2U_PERSIST_BLUETOOTH_DIR|B2U_PERSIST_SPEC|B2U_PERSIST_DEVICE)
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

append_line() {
  printf '%s\n' "$*" >>"$OUT"
}

code_block() {
  echo '```'
  cat
  echo '```'
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
    s/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/<<REDACTED_UUID>>/gi;
    s/^(?:[0-9a-f]{32})$/<<REDACTED_MACHINE_ID>>/;
    s/\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b/<<REDACTED_BT_MAC>>/g;
  '
}

run_shell_block() {
  local timeout_secs="$1"
  local command="$2"
  local status=0
  local tmp

  echo '```'
  tmp="$(mktemp)"
  B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" timeout "$timeout_secs" bash -lc "$command" >"$tmp" 2>&1 || status=$?
  B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream <"$tmp"
  rm -f "$tmp"
  if [[ $status -eq 124 ]]; then
    printf '[timed out after %ss]\n' "$timeout_secs"
  elif [[ $status -ne 0 ]]; then
    printf '[command exited with status %s]\n' "$status"
  fi
  echo '```'
}

cleanup() {
  local exit_code=$?

  trap - EXIT INT TERM

  if [[ $SERVICE_STOPPED_FOR_DEBUG -eq 1 ]]; then
    if ! systemctl start "${B2U_SERVICE_UNIT}"; then
      warn "Failed to restart ${B2U_SERVICE_UNIT} after debug run"
      [[ $exit_code -eq 0 ]] && exit_code=1
    fi
  fi

  if [[ -n "$OUT" && -f "$OUT" ]]; then
    echo "Wrote: $OUT"
  fi

  if [[ -n "$INTERRUPTED_BY_SIGNAL" ]]; then
    case "$INTERRUPTED_BY_SIGNAL" in
      INT) exit 130 ;;
      TERM) exit 143 ;;
    esac
  fi

  exit "$exit_code"
}

trap cleanup EXIT
trap 'INTERRUPTED_BY_SIGNAL="INT"' INT
trap 'INTERRUPTED_BY_SIGNAL="TERM"' TERM

stop_service_for_debug() {
  if systemctl is-active --quiet "${B2U_SERVICE_UNIT}"; then
    systemctl stop "${B2U_SERVICE_UNIT}"
    SERVICE_STOPPED_FOR_DEBUG=1
  fi
}

run_live_debug_block() {
  local command="$1"
  local status=0
  local tmp
  local child_pid=""
  local interrupted=""

  echo '```' >>"$OUT"
  tmp="$(mktemp)"

  if [[ -n "$DURATION" ]]; then
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" timeout "$DURATION" bash -lc "$command" >"$tmp" 2>&1 || status=$?
  else
    trap 'interrupted="INT"; INTERRUPTED_BY_SIGNAL="INT"; [[ -n "$child_pid" ]] && kill -INT -- "-$child_pid" 2>/dev/null || true' INT
    trap 'interrupted="TERM"; INTERRUPTED_BY_SIGNAL="TERM"; [[ -n "$child_pid" ]] && kill -TERM -- "-$child_pid" 2>/dev/null || true' TERM
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" setsid bash -lc "$command" >"$tmp" 2>&1 &
    child_pid=$!
    wait "$child_pid" || status=$?
    trap 'INTERRUPTED_BY_SIGNAL="INT"' INT
    trap 'INTERRUPTED_BY_SIGNAL="TERM"' TERM
  fi

  B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream <"$tmp" >>"$OUT"
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

append_line "# bluetooth_2_usb debug report"
append_line
append_line "_Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")_"
append_line

append_line "## System"
printf '%s\n' "$REDACT_HOSTNAME" | B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream | code_block >>"$OUT"
run_shell_block 5 "uname -a" >>"$OUT"
[[ -f /etc/os-release ]] && run_shell_block 5 "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release" >>"$OUT"
run_shell_block 5 "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true" >>"$OUT"

append_line "## Boot"
printf '%s\n' "boot_dir=${BOOT_DIR}" | code_block >>"$OUT"
if [[ -f "$CONFIG_TXT" ]]; then
  run_shell_block 5 "grep -nE '^\[all\]|dtoverlay=dwc2.*' '$CONFIG_TXT'" >>"$OUT"
else
  echo "missing: $CONFIG_TXT" | code_block >>"$OUT"
fi
if [[ -f "$CMDLINE_TXT" ]]; then
  run_shell_block 5 "cat '$CMDLINE_TXT'" >>"$OUT"
else
  echo "missing: $CMDLINE_TXT" | code_block >>"$OUT"
fi

append_line "## Runtime prerequisites"
run_shell_block 5 "ls /sys/class/udc 2>/dev/null || true" >>"$OUT"
if [[ -d /sys/kernel/config/usb_gadget ]]; then
  echo "/sys/kernel/config/usb_gadget exists" | code_block >>"$OUT"
else
  echo "configfs missing" | code_block >>"$OUT"
fi
printf '%s\n' "overlayfs=$(overlay_status)" | code_block >>"$OUT"
if [ -f "$B2U_READONLY_ENV_FILE" ] && [ -s "$B2U_READONLY_ENV_FILE" ] && [ "$PARSE_ERROR" -eq 1 ]; then
  printf '%s\n' "readonly_mode=<config parse error>" | code_block >>"$OUT"
  printf '%s\n' "bluetooth_state_persistent=<config parse error>" | code_block >>"$OUT"
else
  printf '%s\n' "readonly_mode=$(readonly_mode 2>/dev/null || echo '<error>')" | code_block >>"$OUT"
  printf '%s\n' "bluetooth_state_persistent=$(bluetooth_state_persistent 2>/dev/null && echo yes || echo no)" | code_block >>"$OUT"
fi
[[ -f "$B2U_READONLY_ENV_FILE" ]] && run_shell_block 5 "cat '$B2U_READONLY_ENV_FILE'" >>"$OUT" || true
run_shell_block 5 "findmnt -t overlay,tmpfs 2>/dev/null || true" >>"$OUT"
run_shell_block 5 "findmnt -n -T /var/lib/bluetooth 2>/dev/null || true" >>"$OUT"
run_shell_block 5 "findmnt -n '$B2U_PERSIST_MOUNT' 2>/dev/null || true" >>"$OUT"
[[ -f /etc/machine-id ]] && run_shell_block 5 "cat /etc/machine-id" >>"$OUT" || true
printf '%s\n' "machine_id_valid=$(machine_id_valid && echo yes || echo no)" | code_block >>"$OUT"
if [[ -d /var/lib/bluetooth ]]; then
  run_shell_block 5 "find /var/lib/bluetooth -type f | sort" >>"$OUT"
else
  echo "/var/lib/bluetooth missing" | code_block >>"$OUT"
fi

append_line "## systemd"
printf '%s\n' "service_state_before_debug=${SERVICE_INITIAL_STATE:-unknown}" | code_block >>"$OUT"
run_shell_block 8 "systemctl --no-pager --full status '${B2U_SERVICE_UNIT}' 2>/dev/null || true" >>"$OUT"
run_shell_block 8 "journalctl -b -u '${B2U_SERVICE_UNIT}' -n 200 --no-pager 2>/dev/null || true" >>"$OUT"

append_line "## dmesg"
run_shell_block 8 "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true" >>"$OUT"

append_line "## CLI"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  run_shell_block 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --version" >>"$OUT"
  run_shell_block 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --validate-env" >>"$OUT"

  stop_service_for_debug

  printf '%s\n' "service_stopped_for_live_debug=$([[ $SERVICE_STOPPED_FOR_DEBUG -eq 1 ]] && echo yes || echo no)" | code_block >>"$OUT"
  if [[ -n "$DURATION" ]]; then
    printf '%s\n' "live_debug_duration=${DURATION}s" | code_block >>"$OUT"
  else
    printf '%s\n' "live_debug_duration=until interrupted" | code_block >>"$OUT"
  fi
  printf '%s\n' "live_debug_command=${B2U_DEBUG_CMD}" | code_block >>"$OUT"
  run_live_debug_block "${B2U_DEBUG_CMD}"
else
  echo "missing virtualenv at ${VENV_DIR}" | code_block >>"$OUT"
fi
