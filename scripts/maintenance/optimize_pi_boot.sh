#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../lib/paths.sh
source "${SCRIPTS_DIR}/lib/paths.sh"
# shellcheck source=../lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"
# shellcheck source=../lib/boot.sh
source "${SCRIPTS_DIR}/lib/boot.sh"
# shellcheck source=../lib/pi_boot_optimize.sh
source "${SCRIPTS_DIR}/lib/pi_boot_optimize.sh"

STATIC_IP_MODE=""
STATIC_IP_ADDRESS=""
STATIC_IP_GATEWAY=""
STATIC_IP_DNS=""
DRY_RUN=0
NO_REBOOT=0
ROLLBACK_ONLY=0
MUTATED=0
AUTO_ROLLBACK_ACTIVE=0
INTERFACE_NAME="wlan0"

usage() {
  cat <<EOF
Usage: sudo ./scripts/maintenance/optimize_pi_boot.sh [options]

Reduce Pi boot delays that are not required for bluetooth_2_usb:
- disable cloud-init on hosts that no longer use it
- disable NetworkManager-wait-online.service
- remove ds=nocloud... from cmdline.txt
- optionally freeze the current DHCP IPv4 settings as a static NetworkManager configuration
- when netplan generated transient NetworkManager profiles, persist them as native
  NetworkManager keyfiles and disable the generated /etc/netplan/90-NM-*.yaml overrides

Options:
  --dry-run                   Print the planned changes without mutating the host.
  --rollback                  Restore the previously captured host state from ${B2U_OPTIMIZE_STATE_FILE}.
  --no-reboot                 Do not reboot automatically after apply or explicit rollback.
  --static-ip auto            Freeze the currently active DHCP IPv4 settings as a static profile.
  --static-ip CIDR            Set an explicit static IPv4 address. Requires --gateway and --dns.
  --gateway IPV4              IPv4 gateway used with an explicit --static-ip CIDR.
  --dns CSV                   Comma-separated IPv4 DNS servers used with an explicit --static-ip CIDR.
  -h, --help                  Show this help and exit.
EOF
}

run_or_echo() {
  local description="$1"
  shift

  info "$description"
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '  %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

auto_rollback_on_error() {
  local exit_code=$?

  trap - EXIT
  if [[ $exit_code -ne 0 && $AUTO_ROLLBACK_ACTIVE -eq 1 && $MUTATED -eq 1 ]]; then
    warn "Boot optimization failed after mutating host state. Attempting automatic rollback."
    rollback_boot_optimization_state || warn "Automatic rollback did not complete cleanly."
  fi
  exit "$exit_code"
}

trap auto_rollback_on_error EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --rollback)
      ROLLBACK_ONLY=1
      shift
      ;;
    --no-reboot)
      NO_REBOOT=1
      shift
      ;;
    --static-ip)
      require_value "$1" "${2:-}"
      STATIC_IP_MODE="$2"
      shift 2
      ;;
    --gateway)
      require_value "$1" "${2:-}"
      STATIC_IP_GATEWAY="$2"
      shift 2
      ;;
    --dns)
      require_value "$1" "${2:-}"
      STATIC_IP_DNS="$2"
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

ensure_root
prepare_log "optimize_pi_boot"
require_commands git head nmcli python3 systemctl

if [[ $ROLLBACK_ONLY -eq 1 && -n "$STATIC_IP_MODE" ]]; then
  fail "Do not combine --rollback with --static-ip."
fi

if [[ "$STATIC_IP_MODE" == "auto" ]]; then
  [[ -z "$STATIC_IP_GATEWAY" && -z "$STATIC_IP_DNS" ]] \
    || fail "Do not combine --static-ip auto with --gateway or --dns."
elif [[ -n "$STATIC_IP_MODE" ]]; then
  STATIC_IP_ADDRESS="$STATIC_IP_MODE"
  [[ -n "$STATIC_IP_GATEWAY" ]] \
    || fail "--gateway is required when --static-ip uses an explicit CIDR."
  [[ -n "$STATIC_IP_DNS" ]] \
    || fail "--dns is required when --static-ip uses an explicit CIDR."
else
  [[ -z "$STATIC_IP_GATEWAY" && -z "$STATIC_IP_DNS" ]] \
    || fail "--gateway and --dns require --static-ip."
fi

if [[ $ROLLBACK_ONLY -eq 1 ]]; then
  info "Rolling back boot optimization state from ${B2U_OPTIMIZE_STATE_FILE}"
  [[ $DRY_RUN -eq 0 ]] || fail "--dry-run is not supported together with --rollback."
  rollback_boot_optimization_state
  ok "Boot optimization rollback completed"
  if [[ $NO_REBOOT -eq 0 ]]; then
    info "Rebooting to apply the restored host state"
    trap - EXIT
    systemctl reboot
  else
    warn "Rollback completed. Reboot the Pi manually to restore the previous boot path."
    trap - EXIT
  fi
  exit 0
fi

[[ "$B2U_REPO_ROOT" == "$B2U_INSTALL_DIR" ]] \
  || fail "Run this script from the managed checkout in ${B2U_INSTALL_DIR}."
[[ -d "${B2U_INSTALL_DIR}/.git" ]] \
  || fail "Expected a managed git checkout at ${B2U_INSTALL_DIR}."

CURRENT_BRANCH="$(managed_checkout_branch)" \
  || fail "Refusing to optimize boot from a detached HEAD in ${B2U_INSTALL_DIR}."
if managed_checkout_dirty; then
  fail "Refusing to optimize boot with a dirty managed checkout at ${B2U_INSTALL_DIR}."
fi

info "Managed checkout branch: ${CURRENT_BRANCH}"
print_boot_optimization_snapshot

if [[ $DRY_RUN -eq 0 ]]; then
  info "Running preflight bluetooth_2_usb health check"
  systemctl is-active bluetooth.service >/dev/null
  systemctl is-active "${B2U_SERVICE_UNIT}" >/dev/null
  "${B2U_INSTALL_DIR}/scripts/diagnostics/smoke_test.sh" --verbose
fi

CMDLINE_TXT="$(boot_cmdline_path)"
CLOUD_MARKER_STATE="absent"
WAIT_ONLINE_STATE="$(systemd_unit_enabled_state NetworkManager-wait-online.service)"
CMDLINE_BACKUP_PATH=""
STATIC_IP_STATE=""

if cloud_init_marker_present; then
  CLOUD_MARKER_STATE="present"
fi

if [[ -n "$STATIC_IP_MODE" ]]; then
  STATIC_IP_STATE="$STATIC_IP_MODE"
fi

if [[ $DRY_RUN -eq 0 ]]; then
  CMDLINE_BACKUP_PATH="$(backup_cmdline_for_boot_optimization "$CMDLINE_TXT")"
  write_boot_optimize_state \
    "$CLOUD_MARKER_STATE" \
    "$WAIT_ONLINE_STATE" \
    "$CMDLINE_BACKUP_PATH" \
    "$STATIC_IP_STATE" \
    "$INTERFACE_NAME"
  AUTO_ROLLBACK_ACTIVE=1
fi

run_or_echo "Disable cloud-init for normal boots" disable_cloud_init
MUTATED=1
run_or_echo "Disable NetworkManager-wait-online.service" set_wait_online_enabled_state disabled
run_or_echo "Remove ds=nocloud... from ${CMDLINE_TXT}" remove_nocloud_cmdline_tokens "$CMDLINE_TXT"
run_or_echo "Persist generated NetworkManager profiles and disable netplan 90-NM overrides" \
  persist_netplan_generated_nm_profiles

if [[ "$STATIC_IP_MODE" == "auto" ]]; then
  ACTIVE_CONNECTION="$(active_nm_connection_for_interface "$INTERFACE_NAME")"
  STATIC_IP_ADDRESS="$(current_ipv4_address_for_interface "$INTERFACE_NAME")"
  STATIC_IP_GATEWAY="$(current_ipv4_gateway_for_interface "$INTERFACE_NAME")"
  STATIC_IP_DNS="$(current_ipv4_dns_for_interface "$INTERFACE_NAME")"
  info "Freezing current DHCP IPv4 settings for ${INTERFACE_NAME}: ${STATIC_IP_ADDRESS} via ${STATIC_IP_GATEWAY} dns ${STATIC_IP_DNS}"
  run_or_echo "Apply static IPv4 configuration to ${ACTIVE_CONNECTION}" \
    apply_static_ipv4_configuration "$ACTIVE_CONNECTION" "$STATIC_IP_ADDRESS" "$STATIC_IP_GATEWAY" "$STATIC_IP_DNS"
elif [[ -n "$STATIC_IP_ADDRESS" ]]; then
  ACTIVE_CONNECTION="$(active_nm_connection_for_interface "$INTERFACE_NAME")"
  info "Applying explicit static IPv4 settings for ${INTERFACE_NAME}: ${STATIC_IP_ADDRESS} via ${STATIC_IP_GATEWAY} dns ${STATIC_IP_DNS}"
  run_or_echo "Apply explicit static IPv4 configuration to ${ACTIVE_CONNECTION}" \
    apply_static_ipv4_configuration "$ACTIVE_CONNECTION" "$STATIC_IP_ADDRESS" "$STATIC_IP_GATEWAY" "$STATIC_IP_DNS"
fi

if [[ $DRY_RUN -eq 1 ]]; then
  ok "Dry run completed without mutating host state"
  trap - EXIT
  exit 0
fi

ok "Boot optimization changes applied"
warn "The captured rollback state remains at ${B2U_OPTIMIZE_STATE_FILE} until an explicit rollback clears it."

if [[ $NO_REBOOT -eq 0 ]]; then
  info "Rebooting now so the new boot configuration takes effect"
  AUTO_ROLLBACK_ACTIVE=0
  trap - EXIT
  systemctl reboot
else
  warn "Reboot the Pi manually to apply the new boot settings."
  AUTO_ROLLBACK_ACTIVE=0
  trap - EXIT
fi
