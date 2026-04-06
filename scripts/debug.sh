#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=./lib/common.sh
source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
DURATION=""
REDACT=0
OUT=""
SERVICE_STOPPED_FOR_DEBUG=0
INTERRUPTED_BY_SIGNAL=""
PARSE_ERROR=0
B2U_EFFECTIVE_ARGS="--auto_discover --grab_devices --interrupt_shortcut CTRL+SHIFT+F12"

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
SERVICE_INITIAL_STATE="$(systemctl is-active "${B2U_SERVICE_UNIT}" 2>/dev/null || true)"
if [[ -f "$B2U_ENV_FILE" ]] && [[ -s "$B2U_ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^BLUETOOTH_2_USB_ARGS=\"([^\"]*)\"$ ]] || continue
    B2U_EFFECTIVE_ARGS="${BASH_REMATCH[1]}"
  done <"$B2U_ENV_FILE"
fi
if [[ -x "${VENV_DIR}/bin/bluetooth_2_usb" ]]; then
  B2U_DEBUG_CMD="'${VENV_DIR}/bin/bluetooth_2_usb' ${B2U_EFFECTIVE_ARGS} --debug"
elif [[ -x "${VENV_DIR}/bin/python" ]]; then
  B2U_DEBUG_CMD="'${VENV_DIR}/bin/python' -m bluetooth_2_usb ${B2U_EFFECTIVE_ARGS} --debug"
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

append_line() {
  printf '%s\n' "$*" >>"$OUT"
}

code_block() {
  echo '```'
  perl -0pe 's/(?<!\n)\z/\n/'
  echo '```'
}

append_titled_literal_block() {
  local title="$1"
  shift
  append_line "### ${title}"
  printf '%s\n' "$@" | code_block >>"$OUT"
  append_line
}

append_titled_shell_block() {
  local title="$1"
  local timeout_secs="$2"
  local command="$3"
  append_line "### ${title}"
  run_shell_block "$timeout_secs" "$command" >>"$OUT"
  append_line
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
  B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream <"$tmp" | perl -0pe 's/(?<!\n)\z/\n/'
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
    ok "Wrote: $OUT"
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
  info "Streaming live Bluetooth-2-USB debug output to stdout and $OUT"

  if [[ -n "$DURATION" ]]; then
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" timeout "$DURATION" bash -lc "$command" \
      > >(B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream | tee "$tmp") 2>&1 || status=$?
  else
    trap 'interrupted="INT"; INTERRUPTED_BY_SIGNAL="INT"; [[ -n "$child_pid" ]] && kill -INT -- "-$child_pid" 2>/dev/null || true' INT
    trap 'interrupted="TERM"; INTERRUPTED_BY_SIGNAL="TERM"; [[ -n "$child_pid" ]] && kill -TERM -- "-$child_pid" 2>/dev/null || true' TERM
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" setsid bash -lc "$command" \
      > >(B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream | tee "$tmp") 2>&1 &
    child_pid=$!
    wait "$child_pid" || status=$?
    trap 'INTERRUPTED_BY_SIGNAL="INT"' INT
    trap 'INTERRUPTED_BY_SIGNAL="TERM"' TERM
  fi

  perl -0pe 's/(?<!\n)\z/\n/' "$tmp" >>"$OUT"
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
append_titled_literal_block "Hostname" "$(
  printf '%s\n' "$REDACT_HOSTNAME" | B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream
)"
append_titled_shell_block "Kernel" 5 "uname -a"
[[ -f /etc/os-release ]] && append_titled_shell_block "OS release" 5 "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"
append_titled_shell_block "Hardware model" 5 "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"

append_line "## Boot"
append_titled_literal_block "Boot directory" "boot_dir=${BOOT_DIR}"
if [[ -f "$CONFIG_TXT" ]]; then
  append_titled_shell_block "config.txt dwc2 lines" 5 "grep -nE '^\[all\]|dtoverlay=dwc2.*' '$CONFIG_TXT'"
else
  append_titled_literal_block "config.txt dwc2 lines" "missing: $CONFIG_TXT"
fi
if [[ -f "$CMDLINE_TXT" ]]; then
  append_titled_shell_block "cmdline.txt" 5 "cat '$CMDLINE_TXT'"
else
  append_titled_literal_block "cmdline.txt" "missing: $CMDLINE_TXT"
fi

append_line "## Runtime prerequisites"
append_titled_shell_block "Detected UDC controllers" 5 "ls /sys/class/udc 2>/dev/null || true"
if [[ -d /sys/kernel/config/usb_gadget ]]; then
  append_titled_literal_block "configfs gadget path" "/sys/kernel/config/usb_gadget exists"
else
  append_titled_literal_block "configfs gadget path" "configfs missing"
fi
append_titled_literal_block "OverlayFS status" "overlayfs=$(overlay_status)"
if [ -f "$B2U_READONLY_ENV_FILE" ] && [ -s "$B2U_READONLY_ENV_FILE" ] && [ "$PARSE_ERROR" -eq 1 ]; then
  append_titled_literal_block "Read-only mode" "readonly_mode=<config parse error>"
  append_titled_literal_block "Persistent Bluetooth-state detection" "bluetooth_state_persistent=<config parse error>"
else
  append_titled_literal_block "Read-only mode" "readonly_mode=$(readonly_mode 2>/dev/null || echo '<error>')"
  append_titled_literal_block "Persistent Bluetooth-state detection" "bluetooth_state_persistent=$(bluetooth_state_persistent 2>/dev/null && echo yes || echo no)"
fi
if [[ -f "$B2U_READONLY_ENV_FILE" ]]; then
  append_titled_shell_block "Read-only environment file" 5 "cat '$B2U_READONLY_ENV_FILE'"
fi
append_titled_shell_block "Overlay and tmpfs mounts" 5 "findmnt -t overlay,tmpfs 2>/dev/null || true"
append_titled_shell_block "Bluetooth state mount" 5 "findmnt -n -T /var/lib/bluetooth 2>/dev/null || true"
append_titled_shell_block "Persistent mount target" 5 "findmnt -n '$B2U_PERSIST_MOUNT' 2>/dev/null || true"
if [[ -f /etc/machine-id ]]; then
  append_titled_shell_block "machine-id" 5 "cat /etc/machine-id"
fi
append_titled_literal_block "machine-id validation" "machine_id_valid=$(machine_id_valid && echo yes || echo no)"
if [[ -d /var/lib/bluetooth ]]; then
  append_titled_shell_block "Bluetooth state files" 5 "find /var/lib/bluetooth -type f | sort"
else
  append_titled_literal_block "Bluetooth state files" "/var/lib/bluetooth missing"
fi

append_line "## systemd"
append_titled_literal_block "Initial service state" "service_state_before_debug=${SERVICE_INITIAL_STATE:-unknown}"
append_titled_shell_block "Service status" 8 "systemctl --no-pager --full status '${B2U_SERVICE_UNIT}'"
append_titled_shell_block "Recent service journal" 8 "journalctl -b -u '${B2U_SERVICE_UNIT}' -n 200 --no-pager"

append_line "## dmesg"
append_titled_shell_block "Relevant kernel log lines" 8 "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"

append_line "## CLI"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  append_titled_shell_block "CLI version" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --version"
  append_titled_shell_block "CLI environment validation" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --validate-env"

  stop_service_for_debug

  append_titled_literal_block "Live debug setup" \
    "service_stopped_for_live_debug=$([[ $SERVICE_STOPPED_FOR_DEBUG -eq 1 ]] && echo yes || echo no)" \
    "$([[ -n "$DURATION" ]] && printf 'live_debug_duration=%ss' "$DURATION" || printf 'live_debug_duration=until interrupted')" \
    "live_debug_command=${B2U_DEBUG_CMD}"
  append_line "### Live Bluetooth-2-USB debug output"
  if [[ -n "$DURATION" ]]; then
    info "Live debug duration: ${DURATION}s"
  else
    info "Live debug duration: until interrupted"
  fi
  run_live_debug_block "${B2U_DEBUG_CMD}"
else
  append_titled_literal_block "CLI runtime" "missing virtualenv at ${VENV_DIR}"
fi
