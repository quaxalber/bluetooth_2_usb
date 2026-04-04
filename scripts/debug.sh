#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

INSTALL_DIR="$B2U_DEFAULT_INSTALL_DIR"
SERVICE_NAME="$B2U_DEFAULT_SERVICE_NAME"
VENV_DIR="${INSTALL_DIR}/venv"
DURATION=10
REDACT=0

usage() {
  cat <<EOF
Usage: sudo ./debug.sh [options]
  --dir <path>        Install directory. Default: ${B2U_DEFAULT_INSTALL_DIR}
  --service <name>    Service name. Default: ${B2U_DEFAULT_SERVICE_NAME}
  --venv <path>       Virtualenv path. Default: ${VENV_DIR}
  --duration <sec>    Diagnostic duration. Default: 10
  --redact            Redact host identifiers before writing the report
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) require_value "$1" "${2:-}"; INSTALL_DIR="$2"; VENV_DIR="${INSTALL_DIR}/venv"; shift 2 ;;
    --service) require_value "$1" "${2:-}"; SERVICE_NAME="$2"; shift 2 ;;
    --venv) require_value "$1" "${2:-}"; VENV_DIR="$2"; shift 2 ;;
    --duration) require_value "$1" "${2:-}"; DURATION="$2"; shift 2 ;;
    --redact) REDACT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
mkdir -p "$B2U_DEFAULT_LOG_DIR"
OUT="${B2U_DEFAULT_LOG_DIR}/debug_$(timestamp).md"
BOOT_DIR="$(detect_boot_dir)"
CONFIG_TXT="$(boot_config_path)"
CMDLINE_TXT="$(boot_cmdline_path)"
REDACT_HOSTNAME="${HOSTNAME:-$(hostname)}"

# Load readonly config with error handling to prevent malformed files from aborting report generation
if [ -f "$B2U_READONLY_ENV_FILE" ] && [ -s "$B2U_READONLY_ENV_FILE" ]; then
  # Parse config manually to handle errors gracefully
  B2U_READONLY_MODE="disabled"
  B2U_PERSIST_MOUNT="$B2U_DEFAULT_PERSIST_MOUNT"
  B2U_PERSIST_BLUETOOTH_DIR="${B2U_DEFAULT_PERSIST_MOUNT}/${B2U_DEFAULT_PERSIST_BLUETOOTH_SUBDIR}"
  B2U_PERSIST_SPEC=""
  B2U_PERSIST_DEVICE=""

  parse_error=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "$line" ]] || continue
    if [[ ! "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=\"([^\"]*)\"$ ]]; then
      warn "Malformed $B2U_READONLY_ENV_FILE, skipping readonly entries"
      parse_error=1
      break
    fi
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      B2U_READONLY_MODE|B2U_PERSIST_MOUNT|B2U_PERSIST_BLUETOOTH_DIR|B2U_PERSIST_SPEC|B2U_PERSIST_DEVICE)
        printf -v "$key" '%s' "$value"
        ;;
      *)
        warn "Malformed $B2U_READONLY_ENV_FILE, skipping readonly entries"
        parse_error=1
        break
        ;;
    esac
  done <"$B2U_READONLY_ENV_FILE"
else
  # Set defaults if file doesn't exist
  B2U_READONLY_MODE="disabled"
  B2U_PERSIST_MOUNT="$B2U_DEFAULT_PERSIST_MOUNT"
  B2U_PERSIST_BLUETOOTH_DIR="${B2U_DEFAULT_PERSIST_MOUNT}/${B2U_DEFAULT_PERSIST_BLUETOOTH_SUBDIR}"
  B2U_PERSIST_SPEC=""
  B2U_PERSIST_DEVICE=""
fi

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

{
  echo "# bluetooth_2_usb debug report"
  echo
  echo "_Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")_"
  echo

  echo "## System"
  printf '%s\n' "$REDACT_HOSTNAME" | B2U_REDACT_HOSTNAME="$REDACT_HOSTNAME" redact_stream | code_block
  run_shell_block 5 "uname -a"
  [[ -f /etc/os-release ]] && run_shell_block 5 "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"
  run_shell_block 5 "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"

  echo "## Boot"
  printf '%s\n' "boot_dir=${BOOT_DIR}" | code_block
  if [[ -f "$CONFIG_TXT" ]]; then
    run_shell_block 5 "grep -nE '^\[all\]|dtoverlay=dwc2.*' '$CONFIG_TXT'"
  else
    echo "missing: $CONFIG_TXT" | code_block
  fi
  if [[ -f "$CMDLINE_TXT" ]]; then
    run_shell_block 5 "cat '$CMDLINE_TXT'"
  else
    echo "missing: $CMDLINE_TXT" | code_block
  fi

  echo "## Runtime prerequisites"
  run_shell_block 5 "ls /sys/class/udc 2>/dev/null || true"
  [[ -d /sys/kernel/config/usb_gadget ]] && echo "/sys/kernel/config/usb_gadget exists" | code_block || echo "configfs missing" | code_block
  printf '%s\n' "overlayfs=$(overlay_status)" | code_block
  # Check readonly mode and bluetooth persistence with error handling for malformed config
  if [ -f "$B2U_READONLY_ENV_FILE" ] && [ -s "$B2U_READONLY_ENV_FILE" ] && [ "${parse_error:-0}" -eq 1 ]; then
    printf '%s\n' "readonly_mode=<config parse error>" | code_block
    printf '%s\n' "bluetooth_state_persistent=<config parse error>" | code_block
  else
    printf '%s\n' "readonly_mode=$(readonly_mode 2>/dev/null || echo '<error>')" | code_block
    printf '%s\n' "bluetooth_state_persistent=$(bluetooth_state_persistent 2>/dev/null && echo yes || echo no)" | code_block
  fi
  [[ -f "$B2U_READONLY_ENV_FILE" ]] && run_shell_block 5 "cat '$B2U_READONLY_ENV_FILE'" || true
  run_shell_block 5 "findmnt -t overlay,tmpfs 2>/dev/null || true"
  run_shell_block 5 "findmnt -n -T /var/lib/bluetooth 2>/dev/null || true"
  run_shell_block 5 "findmnt -n '$B2U_PERSIST_MOUNT' 2>/dev/null || true"
  [[ -f /etc/machine-id ]] && run_shell_block 5 "cat /etc/machine-id" || true
  printf '%s\n' "machine_id_valid=$(machine_id_valid && echo yes || echo no)" | code_block
  [[ -d /var/lib/bluetooth ]] && run_shell_block 5 "find /var/lib/bluetooth -type f | sort" || echo "/var/lib/bluetooth missing" | code_block

  echo "## systemd"
  run_shell_block 5 "systemctl is-active '${SERVICE_NAME}.service' 2>/dev/null || true"
  run_shell_block 8 "systemctl --no-pager --full status '${SERVICE_NAME}.service' 2>/dev/null || true"
  run_shell_block 8 "journalctl -b -u '${SERVICE_NAME}.service' -n 200 --no-pager 2>/dev/null || true"

  echo "## dmesg"
  run_shell_block 8 "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"

  echo "## CLI"
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    run_shell_block 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --version"
    run_shell_block 5 "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --validate-env"
    run_shell_block "${DURATION}" "'${VENV_DIR}/bin/python' -m bluetooth_2_usb --dry-run --debug 2>&1"
  else
    echo "missing virtualenv at ${VENV_DIR}" | code_block
  fi
} >"$OUT"

echo "Wrote: $OUT"