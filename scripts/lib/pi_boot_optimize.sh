#!/usr/bin/env bash

if [[ -n "${B2U_PI_BOOT_OPTIMIZE_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_PI_BOOT_OPTIMIZE_SH_SOURCED=1

_b2u_pi_boot_optimize_dir="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./paths.sh
source "${_b2u_pi_boot_optimize_dir}/paths.sh"
# shellcheck source=./common.sh
source "${_b2u_pi_boot_optimize_dir}/common.sh"
# shellcheck source=./boot.sh
source "${_b2u_pi_boot_optimize_dir}/boot.sh"
unset _b2u_pi_boot_optimize_dir

readonly B2U_CLOUD_INIT_UNITS=(
  cloud-init-main.service
  cloud-init-local.service
  cloud-init-network.service
  cloud-config.service
  cloud-final.service
)

managed_git() {
  git -c safe.directory="${B2U_INSTALL_DIR}" -C "${B2U_INSTALL_DIR}" "$@"
}

managed_checkout_branch() {
  managed_git symbolic-ref --quiet --short HEAD
}

managed_checkout_dirty() {
  [[ -n "$(managed_git status --porcelain --untracked-files=all)" ]]
}

systemd_unit_enabled_state() {
  local unit="$1"

  if ! systemctl list-unit-files --all --full --no-legend "$unit" >/dev/null 2>&1; then
    printf '%s\n' "missing"
    return 0
  fi

  if systemctl is-enabled "$unit" >/dev/null 2>&1; then
    printf '%s\n' "enabled"
  else
    printf '%s\n' "disabled"
  fi
}

nmcli_connection_get() {
  local connection="$1"
  local field="$2"

  nmcli --get-values "$field" connection show "$connection" 2>/dev/null | head -n 1
}

active_nm_connection_for_interface() {
  local interface_name="${1:-wlan0}"
  local connection_name

  connection_name="$(
    nmcli --get-values GENERAL.CONNECTION device show "$interface_name" 2>/dev/null \
      | head -n 1
  )"
  [[ -n "$connection_name" && "$connection_name" != "--" ]] \
    || fail "No active NetworkManager connection found for ${interface_name}."
  printf '%s\n' "$connection_name"
}

current_ipv4_address_for_interface() {
  local interface_name="${1:-wlan0}"
  local address

  address="$(
    nmcli --get-values IP4.ADDRESS device show "$interface_name" 2>/dev/null | head -n 1
  )"
  [[ -n "$address" && "$address" != "--" ]] \
    || fail "Could not determine the current IPv4 address for ${interface_name}."
  printf '%s\n' "$address"
}

current_ipv4_gateway_for_interface() {
  local interface_name="${1:-wlan0}"
  local gateway

  gateway="$(
    nmcli --get-values IP4.GATEWAY device show "$interface_name" 2>/dev/null | head -n 1
  )"
  [[ -n "$gateway" && "$gateway" != "--" ]] \
    || fail "Could not determine the current IPv4 gateway for ${interface_name}."
  printf '%s\n' "$gateway"
}

current_ipv4_dns_for_interface() {
  local interface_name="${1:-wlan0}"
  local dns_csv=""
  local dns_servers=()
  local line

  while IFS= read -r line; do
    line="${line##*:}"
    [[ -n "$line" && "$line" != "--" ]] || continue
    dns_servers+=("$line")
  done < <(nmcli -t -f IP4.DNS device show "$interface_name" 2>/dev/null)

  [[ ${#dns_servers[@]} -gt 0 ]] \
    || fail "Could not determine the current IPv4 DNS servers for ${interface_name}."

  dns_csv="$(printf '%s,' "${dns_servers[@]}")"
  printf '%s\n' "${dns_csv%,}"
}

capture_nm_connection_state() {
  local connection="$1"

  printf '%s\n' "B2U_NM_PROFILE=$(printf '%q' "$connection")"
  printf '%s\n' "B2U_ORIG_IPV4_METHOD=$(printf '%q' "$(nmcli_connection_get "$connection" ipv4.method)")"
  printf '%s\n' "B2U_ORIG_IPV4_ADDRESSES=$(printf '%q' "$(nmcli_connection_get "$connection" ipv4.addresses)")"
  printf '%s\n' "B2U_ORIG_IPV4_GATEWAY=$(printf '%q' "$(nmcli_connection_get "$connection" ipv4.gateway)")"
  printf '%s\n' "B2U_ORIG_IPV4_DNS=$(printf '%q' "$(nmcli_connection_get "$connection" ipv4.dns)")"
  printf '%s\n' "B2U_ORIG_IPV4_IGNORE_AUTO_DNS=$(printf '%q' "$(nmcli_connection_get "$connection" ipv4.ignore-auto-dns)")"
}

write_boot_optimize_state() {
  local cloud_marker_state="$1"
  local wait_online_state="$2"
  local cmdline_backup_path="$3"
  local static_ip_mode="$4"
  local interface_name="$5"
  local tmp_file
  local unit
  local connection=""

  mkdir -p "$B2U_STATE_DIR"
  tmp_file="${B2U_OPTIMIZE_STATE_FILE}.tmp.$$"

  if [[ -n "$static_ip_mode" ]]; then
    connection="$(active_nm_connection_for_interface "$interface_name")"
  fi

  {
    printf '%s\n' "B2U_CLOUD_INIT_DISABLED_MARKER_PRESENT=$(printf '%q' "$cloud_marker_state")"
    printf '%s\n' "B2U_WAIT_ONLINE_STATE=$(printf '%q' "$wait_online_state")"
    printf '%s\n' "B2U_CMDLINE_BACKUP_PATH=$(printf '%q' "$cmdline_backup_path")"
    printf '%s\n' "B2U_STATIC_IP_MODE=$(printf '%q' "$static_ip_mode")"
    printf '%s\n' "B2U_STATIC_IP_INTERFACE=$(printf '%q' "$interface_name")"
    for unit in "${B2U_CLOUD_INIT_UNITS[@]}"; do
      printf '%s\n' "${unit//[^A-Za-z0-9]/_}=$(printf '%q' "$(systemd_unit_enabled_state "$unit")")"
    done
    if [[ -n "$connection" ]]; then
      capture_nm_connection_state "$connection"
    fi
  } >"$tmp_file"

  chmod 0600 "$tmp_file"
  mv "$tmp_file" "$B2U_OPTIMIZE_STATE_FILE"
}

load_boot_optimize_state() {
  [[ -f "$B2U_OPTIMIZE_STATE_FILE" ]] \
    || fail "No boot optimization state file found at ${B2U_OPTIMIZE_STATE_FILE}."
  # shellcheck disable=SC1090
  source "$B2U_OPTIMIZE_STATE_FILE"
}

cloud_init_marker_present() {
  [[ -f /etc/cloud/cloud-init.disabled ]]
}

disable_cloud_init() {
  local unit

  mkdir -p /etc/cloud
  : >/etc/cloud/cloud-init.disabled
  for unit in "${B2U_CLOUD_INIT_UNITS[@]}"; do
    if systemctl list-unit-files --all --full --no-legend "$unit" >/dev/null 2>&1; then
      systemctl disable "$unit" >/dev/null 2>&1 || true
    fi
  done
}

restore_cloud_init_state() {
  local marker_state="$1"
  local unit
  local unit_var
  local unit_state

  if [[ "$marker_state" == "present" ]]; then
    mkdir -p /etc/cloud
    : >/etc/cloud/cloud-init.disabled
  else
    rm -f /etc/cloud/cloud-init.disabled
  fi

  for unit in "${B2U_CLOUD_INIT_UNITS[@]}"; do
    unit_var="${unit//[^A-Za-z0-9]/_}"
    unit_state="${!unit_var:-missing}"
    [[ "$unit_state" != "missing" ]] || continue
    if [[ "$unit_state" == "enabled" ]]; then
      systemctl enable "$unit" >/dev/null 2>&1 || true
    else
      systemctl disable "$unit" >/dev/null 2>&1 || true
    fi
  done
}

set_wait_online_enabled_state() {
  local desired_state="$1"
  local unit="NetworkManager-wait-online.service"

  if ! systemctl list-unit-files --all --full --no-legend "$unit" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$desired_state" == "enabled" ]]; then
    systemctl enable "$unit" >/dev/null 2>&1 || true
  else
    systemctl disable "$unit" >/dev/null 2>&1 || true
  fi
}

remove_nocloud_cmdline_tokens() {
  local cmdline_file="$1"
  local tmp_file

  [[ -f "$cmdline_file" ]] || fail "Boot cmdline file not found: ${cmdline_file}"
  [[ -w "$cmdline_file" ]] || fail "Boot cmdline file is not writable: ${cmdline_file}"

  tmp_file="${cmdline_file}.tmp.$$"
  python3 - "$cmdline_file" "$tmp_file" <<'PY'
from pathlib import Path
import sys

source_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
tokens = source_path.read_text(encoding="utf-8").strip().split()
filtered = [token for token in tokens if not token.startswith("ds=nocloud")]
target_path.write_text(" ".join(filtered) + "\n", encoding="utf-8")
PY
  mv "$tmp_file" "$cmdline_file"
}

backup_cmdline_for_boot_optimization() {
  local cmdline_file="$1"
  local backup_path=""

  backup_path="${cmdline_file}.optimize_pi_boot.bak.$(timestamp)"
  cp -a "$cmdline_file" "$backup_path"
  printf '%s\n' "$backup_path"
}

restore_cmdline_backup() {
  local backup_path="$1"
  local cmdline_file

  [[ -n "$backup_path" ]] || fail "Boot cmdline backup path is empty."
  [[ -f "$backup_path" ]] || fail "Boot cmdline backup not found: ${backup_path}"

  cmdline_file="${backup_path%.optimize_pi_boot.bak.*}"
  cp -a "$backup_path" "$cmdline_file"
}

apply_static_ipv4_configuration() {
  local connection="$1"
  local address="$2"
  local gateway="$3"
  local dns_csv="$4"

  nmcli connection modify "$connection" \
    ipv4.method manual \
    ipv4.addresses "$address" \
    ipv4.gateway "$gateway" \
    ipv4.dns "$dns_csv" \
    ipv4.ignore-auto-dns yes
}

restore_nm_connection_state() {
  local connection="$1"
  local method="$2"
  local addresses="$3"
  local gateway="$4"
  local dns_csv="$5"
  local ignore_auto_dns="$6"

  [[ -n "$connection" ]] || return 0
  [[ -n "$method" ]] || return 0

  nmcli connection modify "$connection" \
    ipv4.method "$method" \
    ipv4.addresses "${addresses:-}" \
    ipv4.gateway "${gateway:-}" \
    ipv4.dns "${dns_csv:-}" \
    ipv4.ignore-auto-dns "${ignore_auto_dns:-no}"
}

print_boot_optimization_snapshot() {
  info "Current boot timing snapshot:"
  systemd-analyze time || true
  systemd-analyze blame | head -n 10 || true
  systemd-analyze critical-chain bluetooth_2_usb.service || true
}

rollback_boot_optimization_state() {
  load_boot_optimize_state

  restore_nm_connection_state \
    "${B2U_NM_PROFILE:-}" \
    "${B2U_ORIG_IPV4_METHOD:-}" \
    "${B2U_ORIG_IPV4_ADDRESSES:-}" \
    "${B2U_ORIG_IPV4_GATEWAY:-}" \
    "${B2U_ORIG_IPV4_DNS:-}" \
    "${B2U_ORIG_IPV4_IGNORE_AUTO_DNS:-no}"

  if [[ -n "${B2U_CMDLINE_BACKUP_PATH:-}" ]]; then
    restore_cmdline_backup "$B2U_CMDLINE_BACKUP_PATH"
  fi

  restore_cloud_init_state "${B2U_CLOUD_INIT_DISABLED_MARKER_PRESENT:-absent}"
  set_wait_online_enabled_state "${B2U_WAIT_ONLINE_STATE:-disabled}"

  rm -f "$B2U_OPTIMIZE_STATE_FILE"
}
