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
    --dir) INSTALL_DIR="$2"; VENV_DIR="${INSTALL_DIR}/venv"; shift 2 ;;
    --service) SERVICE_NAME="$2"; shift 2 ;;
    --venv) VENV_DIR="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
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
load_readonly_config

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
  [[ -f "$CONFIG_TXT" ]] && run_shell_block 5 "grep -nE '^\[all\]|dtoverlay=dwc2.*' '$CONFIG_TXT'" || echo "missing: $CONFIG_TXT" | code_block
  [[ -f "$CMDLINE_TXT" ]] && run_shell_block 5 "cat '$CMDLINE_TXT'" || echo "missing: $CMDLINE_TXT" | code_block

  echo "## Runtime prerequisites"
  run_shell_block 5 "ls /sys/class/udc 2>/dev/null || true"
  [[ -d /sys/kernel/config/usb_gadget ]] && echo "/sys/kernel/config/usb_gadget exists" | code_block || echo "configfs missing" | code_block
  printf '%s\n' "overlayfs=$(overlay_status)" | code_block
  printf '%s\n' "readonly_mode=$(readonly_mode)" | code_block
  printf '%s\n' "bluetooth_state_persistent=$(bluetooth_state_persistent && echo yes || echo no)" | code_block
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
  run_shell_block 8 "dmesg | egrep -i 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"

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
