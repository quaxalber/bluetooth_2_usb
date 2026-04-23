#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}"
# shellcheck source=./lib/paths.sh
source "${SCRIPTS_DIR}/lib/paths.sh"
# shellcheck source=./lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"
# shellcheck source=./lib/bluetooth.sh
source "${SCRIPTS_DIR}/lib/bluetooth.sh"
# shellcheck source=./lib/boot.sh
source "${SCRIPTS_DIR}/lib/boot.sh"
# shellcheck source=./lib/readonly.sh
source "${SCRIPTS_DIR}/lib/readonly.sh"

VENV_DIR="${B2U_INSTALL_DIR}/venv"
DURATION=""
REPORT_FILE=""
REPORT_BODY=""
SERVICE_WAS_STOPPED=0
STOP_SIGNAL=""
LIVE_DEBUG_STATUS=0
REDACT_HOSTNAME=""
PARSE_ERROR=0

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
      [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] \
        || fail "--duration must be a positive integer (seconds)."
      DURATION="$2"
      shift 2
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

write_heading() {
  printf '## %s\n\n' "$1" >>"$REPORT_BODY"
}

write_text_block() {
  local title="$1"
  shift

  write_heading "$title"
  printf '```text\n' >>"$REPORT_BODY"
  if [[ $# -eq 0 ]]; then
    printf '<no output>\n' >>"$REPORT_BODY"
  else
    printf '%s\n' "$@" >>"$REPORT_BODY"
  fi
  printf '```\n\n' >>"$REPORT_BODY"
}

write_command_block() {
  local title="$1"
  local timeout_secs="$2"
  local command="$3"
  local tmp
  local status=0
  local timed_out=0

  tmp="$(mktemp)"
  if run_command_with_timeout_tracking "$timeout_secs" "$command" "$tmp"; then
    status=0
  else
    status=$?
  fi
  timed_out=$TIMEOUT_EXPIRED

  write_heading "$title"
  printf '```console\n' >>"$REPORT_BODY"
  if [[ -s "$tmp" ]]; then
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream <"$tmp" >>"$REPORT_BODY"
    [[ "$(tail -c 1 "$tmp" 2>/dev/null || true)" == "" ]] || printf '\n' >>"$REPORT_BODY"
  else
    printf '<no output>\n' >>"$REPORT_BODY"
  fi
  if [[ $timed_out -eq 1 ]]; then
    printf '[timed out after %ss]\n' "$timeout_secs" >>"$REPORT_BODY"
  elif [[ $status -ne 0 ]]; then
    printf '[command exited with status %s]\n' "$status" >>"$REPORT_BODY"
  fi
  printf '```\n\n' >>"$REPORT_BODY"

  rm -f "$tmp"
}

TIMEOUT_EXPIRED=0

terminate_process_group() {
  local child_pid="$1"

  [[ -n "$child_pid" ]] || return 0
  if kill -0 -- "-$child_pid" 2>/dev/null || kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM -- "-$child_pid" 2>/dev/null || kill -TERM "$child_pid" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$child_pid" 2>/dev/null || kill -KILL "$child_pid" 2>/dev/null || true
  fi
}

run_command_with_timeout_tracking() {
  local timeout_secs="$1"
  local command="$2"
  local output_path="$3"
  local status=0
  local timed_out_marker=""
  local child_pid=""
  local watcher_pid=""

  TIMEOUT_EXPIRED=0
  timed_out_marker="$(mktemp)"
  rm -f "$timed_out_marker"

  setsid bash --noprofile --norc -c "$command" >"$output_path" 2>&1 &
  child_pid=$!
  (
    sleep "$timeout_secs"
    if kill -0 -- "-$child_pid" 2>/dev/null || kill -0 "$child_pid" 2>/dev/null; then
      : >"$timed_out_marker"
      terminate_process_group "$child_pid"
    fi
  ) &
  watcher_pid=$!

  wait "$child_pid" || status=$?
  if [[ -n "${STOP_SIGNAL:-}" && $status -ne 0 ]]; then
    terminate_process_group "$child_pid"
    wait "$child_pid" 2>/dev/null || true
  fi
  kill "$watcher_pid" 2>/dev/null || true
  wait "$watcher_pid" 2>/dev/null || true

  if [[ -f "$timed_out_marker" ]]; then
    TIMEOUT_EXPIRED=1
  fi
  rm -f "$timed_out_marker"

  return "$status"
}

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
  local timed_out=0

  tmp="$(mktemp)"
  fifo="$(mktemp -u)"
  mkfifo "$fifo"

  write_heading "Live Bluetooth-2-USB debug output"
  printf '```console\n' >>"$REPORT_BODY"

  tee "$tmp" <"$fifo" &
  tee_pid=$!

  info "Streaming live Bluetooth-2-USB debug output to stdout and ${REPORT_FILE}"

  if [[ -n "$DURATION" ]]; then
    info "Live debug duration: ${DURATION}s"
    if run_command_with_timeout_tracking "$DURATION" "$command" "$fifo"; then
      status=0
    else
      status=$?
    fi
    timed_out=$TIMEOUT_EXPIRED
  else
    info "Live debug duration: until interrupted"
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
    B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream <"$tmp" >>"$REPORT_BODY"
    [[ "$(tail -c 1 "$tmp" 2>/dev/null || true)" == "" ]] || printf '\n' >>"$REPORT_BODY"
  else
    printf '<no output>\n' >>"$REPORT_BODY"
  fi

  if [[ $timed_out -eq 1 ]]; then
    printf '[timed out after %ss]\n' "$DURATION" >>"$REPORT_BODY"
  elif [[ $status -ne 0 ]]; then
    [[ -n "$interrupted" ]] || printf '[command exited with status %s]\n' "$status" >>"$REPORT_BODY"
  fi
  if [[ -n "$interrupted" ]]; then
    printf '[interrupted by %s]\n' "$interrupted" >>"$REPORT_BODY"
  fi
  printf '```\n\n' >>"$REPORT_BODY"

  rm -f "$tmp"

  if [[ -n "$interrupted" ]]; then
    case "$interrupted" in
      INT) return 130 ;;
      TERM) return 143 ;;
    esac
  fi
  if [[ $timed_out -eq 1 ]]; then
    return 0
  fi
  return "$status"
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

  if [[ $LIVE_DEBUG_STATUS -ne 0 && $exit_code -eq 0 ]]; then
    exit_code=$LIVE_DEBUG_STATUS
  fi

  if [[ -n "$REPORT_BODY" && -f "$REPORT_BODY" ]] && [[ -n "$REPORT_FILE" ]]; then
    {
      printf '# bluetooth_2_usb debug report\n\n'
      printf '_Generated: %s_\n\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
      cat "$REPORT_BODY"
    } >"$REPORT_FILE"
    ok "Wrote: $REPORT_FILE"
  fi

  [[ -n "${REPORT_BODY:-}" ]] && rm -f -- "$REPORT_BODY"

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

ensure_root
mkdir -p "$B2U_LOG_DIR"
REPORT_FILE="${B2U_LOG_DIR}/debug_$(timestamp).md"
REPORT_BODY="$(mktemp)"
REDACT_HOSTNAME="${HOSTNAME:-$(hostname)}"

BOOT_DIR="$(detect_boot_dir)"
CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
INITIAL_SERVICE_STATE="$(systemctl is-active "${B2U_SERVICE_UNIT}" 2>/dev/null || true)"

if (load_readonly_config) >/dev/null 2>&1; then
  load_readonly_config
else
  PARSE_ERROR=1
fi

DEBUG_CMD=""
CONFIG_SUMMARY_JSON=""
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  DEBUG_CMD="$("${VENV_DIR}/bin/python" -m bluetooth_2_usb.service_config --print-shell-command --append-debug 2>/dev/null || true)"
  CONFIG_SUMMARY_JSON="$("${VENV_DIR}/bin/python" -m bluetooth_2_usb.service_config --print-summary-json 2>/dev/null || true)"
fi

readonly_mode_summary="readonly_mode=<config parse error>"
bluetooth_state_summary="bluetooth_state_persistent=no"
if [[ $PARSE_ERROR -eq 0 ]]; then
  readonly_mode_summary="readonly_mode=$(readonly_mode)"
  if bluetooth_state_persistent 2>/dev/null; then
    bluetooth_state_summary="bluetooth_state_persistent=yes"
  fi
fi

write_text_block "System summary" \
  "boot_dir=${BOOT_DIR}" \
  "initial_service_state=${INITIAL_SERVICE_STATE:-unknown}" \
  "overlayfs=$(overlay_status)" \
  "${readonly_mode_summary}" \
  "${bluetooth_state_summary}"

write_command_block "Kernel" 5 "uname -a"
[[ -f /etc/os-release ]] && write_command_block "OS release" 5 "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"
write_command_block "Hardware model" 5 "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"
write_command_block "config.txt dwc2 lines" 5 "grep -nE '^\[all\]|dtoverlay=dwc2.*' '$CONFIG_TXT' 2>/dev/null || printf 'missing or no dwc2 lines: %s\n' '$CONFIG_TXT'"
write_command_block "cmdline.txt" 5 "cat '$CMDLINE_TXT' 2>/dev/null || printf 'missing: %s\n' '$CMDLINE_TXT'"
write_command_block "UDC controllers" 5 "ls /sys/class/udc 2>/dev/null || true"
write_command_block "Overlay and tmpfs mounts" 5 "findmnt -t overlay,tmpfs 2>/dev/null || true"
write_command_block "Bluetooth state mount" 5 "findmnt -n -T /var/lib/bluetooth 2>/dev/null || true"
write_command_block "Persistent mount target" 5 "findmnt -n '$B2U_PERSIST_MOUNT' 2>/dev/null || true"
if [[ -f "$B2U_READONLY_ENV_FILE" ]]; then
  write_command_block "Read-only environment file" 5 "cat '$B2U_READONLY_ENV_FILE'"
fi
write_command_block "Service status" 8 "systemctl --no-pager --full status '${B2U_SERVICE_UNIT}'"
write_command_block "Recent service journal" 8 "journalctl -b -u '${B2U_SERVICE_UNIT}' -n 200 --no-pager"
write_command_block "bluetooth.service status" 8 "systemctl --no-pager --full status bluetooth.service"
write_command_block "Relevant kernel log lines" 8 "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"
write_command_block "bluetoothctl show" 8 "bluetoothctl show"
write_command_block "Paired devices" 8 "bluetoothctl devices Paired"
write_command_block "btmgmt info" 8 "btmgmt info"
write_command_block "rfkill bluetooth state" 8 "rfkill list bluetooth 2>/dev/null || true; for type_file in /sys/class/rfkill/rfkill*/type; do [[ -f \"\$type_file\" ]] || continue; [[ \"\$(cat \"\$type_file\" 2>/dev/null || true)\" == \"bluetooth\" ]] || continue; rfkill_dir=\$(dirname \"\$type_file\"); printf '%s type=bluetooth soft=%s hard=%s state=%s\n' \"\$(basename \"\$rfkill_dir\")\" \"\$(cat \"\$rfkill_dir/soft\" 2>/dev/null || printf '?')\" \"\$(cat \"\$rfkill_dir/hard\" 2>/dev/null || printf '?')\" \"\$(cat \"\$rfkill_dir/state\" 2>/dev/null || printf '?')\"; done"

if [[ -x "${VENV_DIR}/bin/python" ]]; then
  write_command_block "CLI version" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --version"
  write_command_block "CLI environment validation" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --validate-env"
  write_command_block "Service config summary" 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb.service_config --print-summary-json"
  write_command_block "Device inventory (json)" 8 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --list_devices --output json"

  stop_service_for_debug
  write_text_block "Live debug setup" \
    "service_stopped_for_live_debug=$([[ $SERVICE_WAS_STOPPED -eq 1 ]] && echo yes || echo no)" \
    "$([[ -n "$DURATION" ]] && printf 'live_debug_duration=%ss' "$DURATION" || printf 'live_debug_duration=until interrupted')" \
    "$(
      printf 'live_debug_command=%s\n' "${DEBUG_CMD:-<missing>}" \
        | B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream
    )"

  if [[ -n "$DEBUG_CMD" ]]; then
    run_live_debug_block "${DEBUG_CMD}" || LIVE_DEBUG_STATUS=$?
  else
    write_text_block "Live Bluetooth-2-USB debug output" "Could not build debug command from structured runtime config."
    LIVE_DEBUG_STATUS=1
  fi
else
  write_text_block "CLI runtime" "missing virtualenv at ${VENV_DIR}"
  LIVE_DEBUG_STATUS=1
fi
