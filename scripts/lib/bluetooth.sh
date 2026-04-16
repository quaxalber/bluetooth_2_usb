#!/usr/bin/env bash

if [[ -n "${B2U_BLUETOOTH_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_BLUETOOTH_SH_SOURCED=1

_b2u_bluetooth_lib_dir="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./paths.sh
source "${_b2u_bluetooth_lib_dir}/paths.sh"
# shellcheck source=./common.sh
source "${_b2u_bluetooth_lib_dir}/common.sh"
unset _b2u_bluetooth_lib_dir

bluetoothctl_show() {
  bluetoothctl show
}

bluetoothctl_paired_devices() {
  bluetoothctl devices Paired
}

btmgmt_info() {
  btmgmt info
}

bluetooth_rfkill_root() {
  printf '%s\n' "${B2U_RFKILL_ROOT:-/sys/class/rfkill}"
}

bluetooth_controller_powered() {
  bluetoothctl_show 2>/dev/null | grep -Eq '^[[:space:]]*Powered:[[:space:]]+yes$'
}

bluetooth_paired_count() {
  bluetoothctl_paired_devices 2>/dev/null | grep -c '^Device ' || true
}

bluetooth_rfkill_entries() {
  local type_file=""
  local rfkill_dir=""
  local soft=""
  local hard=""
  local state=""
  local name=""
  local found=1

  for type_file in "$(bluetooth_rfkill_root)"/rfkill*/type; do
    [[ -f "$type_file" ]] || continue
    if [[ "$(cat "$type_file" 2>/dev/null || true)" != "bluetooth" ]]; then
      continue
    fi

    found=0
    rfkill_dir="$(dirname "$type_file")"
    name="$(basename "$rfkill_dir")"
    soft="$(cat "${rfkill_dir}/soft" 2>/dev/null || printf '%s' '?')"
    hard="$(cat "${rfkill_dir}/hard" 2>/dev/null || printf '%s' '?')"
    state="$(cat "${rfkill_dir}/state" 2>/dev/null || printf '%s' '?')"
    printf '%s type=bluetooth soft=%s hard=%s state=%s\n' "$name" "$soft" "$hard" "$state"
  done

  return "$found"
}

bluetooth_rfkill_blocked() {
  local type_file=""
  local rfkill_dir=""
  local found=1
  local soft=""
  local hard=""
  local state=""

  for type_file in "$(bluetooth_rfkill_root)"/rfkill*/type; do
    [[ -f "$type_file" ]] || continue
    if [[ "$(cat "$type_file" 2>/dev/null || true)" != "bluetooth" ]]; then
      continue
    fi

    found=0
    rfkill_dir="$(dirname "$type_file")"
    soft="$(cat "${rfkill_dir}/soft" 2>/dev/null || printf '%s' '?')"
    hard="$(cat "${rfkill_dir}/hard" 2>/dev/null || printf '%s' '?')"
    state="$(cat "${rfkill_dir}/state" 2>/dev/null || printf '%s' '?')"
    if [[ "$soft" == "1" || "$hard" == "1" || "$state" == "0" ]]; then
      return 0
    fi
  done

  [[ $found -eq 0 ]] || return 1
  return 1
}

clear_bluetooth_rfkill_soft_blocks() {
  local type_file=""
  local rfkill_dir=""
  local name=""
  local soft=""
  local hard=""
  local state=""
  local found=1

  for type_file in "$(bluetooth_rfkill_root)"/rfkill*/type; do
    [[ -f "$type_file" ]] || continue
    if [[ "$(cat "$type_file" 2>/dev/null || true)" != "bluetooth" ]]; then
      continue
    fi

    found=0
    rfkill_dir="$(dirname "$type_file")"
    name="$(basename "$rfkill_dir")"
    soft="$(cat "${rfkill_dir}/soft" 2>/dev/null || printf '%s' '?')"
    hard="$(cat "${rfkill_dir}/hard" 2>/dev/null || printf '%s' '?')"
    state="$(cat "${rfkill_dir}/state" 2>/dev/null || printf '%s' '?')"

    if [[ "$hard" == "1" ]]; then
      warn "Bluetooth rfkill ${name} is hard-blocked; leaving it unchanged."
      continue
    fi

    if [[ "$soft" != "1" ]]; then
      info "Bluetooth rfkill ${name} is already unblocked (soft=${soft} state=${state})."
      continue
    fi

    if printf '%s\n' 0 >"${rfkill_dir}/soft" 2>/dev/null; then
      soft="$(cat "${rfkill_dir}/soft" 2>/dev/null || printf '%s' '?')"
      state="$(cat "${rfkill_dir}/state" 2>/dev/null || printf '%s' '?')"
      if [[ "$soft" == "0" ]]; then
        ok "Cleared Bluetooth rfkill soft block for ${name} (state=${state})."
      else
        warn "Attempted to clear Bluetooth rfkill ${name}, but soft=${soft} afterwards."
      fi
      continue
    fi

    warn "Failed to clear Bluetooth rfkill soft block for ${name}."
  done

  if [[ $found -eq 1 ]]; then
    info "No bluetooth rfkill entries found; skipping soft-block cleanup."
  fi
  return 0
}
