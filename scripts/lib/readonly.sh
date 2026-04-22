#!/usr/bin/env bash

if [[ -n "${B2U_READONLY_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_READONLY_SH_SOURCED=1

_b2u_readonly_lib_dir="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./paths.sh
source "${_b2u_readonly_lib_dir}/paths.sh"
# shellcheck source=./common.sh
source "${_b2u_readonly_lib_dir}/common.sh"
unset _b2u_readonly_lib_dir

overlay_status() {
  local state

  if ! command -v raspi-config >/dev/null 2>&1; then
    printf '%s\n' "unknown"
    return
  fi

  state="$(raspi-config nonint get_overlay_now 2>/dev/null | tr -d '[:space:]')"
  case "$state" in
    0) printf '%s\n' "enabled" ;;
    1) printf '%s\n' "disabled" ;;
    *) printf '%s\n' "unknown" ;;
  esac
}

root_overlay_active() {
  [[ "$(findmnt -n -o FSTYPE --target / 2>/dev/null || true)" == "overlay" ]]
}

root_overlay_report() {
  findmnt -n -o TARGET,SOURCE,FSTYPE,OPTIONS --target / 2>/dev/null || true
}

readonly_stack_packages_healthy() {
  local pkg status

  for pkg in overlayroot cryptsetup cryptsetup-bin initramfs-tools; do
    status="$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)"
    [[ "$status" == "install ok installed" ]] || return 1
  done
}

readonly_stack_package_report() {
  local pkg status

  for pkg in overlayroot cryptsetup cryptsetup-bin initramfs-tools; do
    status="$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)"
    [[ -n "$status" ]] || status="not installed"
    printf '%s: %s\n' "$pkg" "$status"
  done
}

machine_id_valid() {
  [[ -f /etc/machine-id ]] || return 1
  grep -Eq '^[0-9a-f]{32}$' /etc/machine-id
}

load_readonly_config() {
  B2U_READONLY_MODE="disabled"
  B2U_PERSIST_MOUNT="$B2U_PERSIST_MOUNT_PATH"
  B2U_PERSIST_BLUETOOTH_DIR="${B2U_PERSIST_MOUNT_PATH}/${B2U_PERSIST_BLUETOOTH_SUBDIR}"
  B2U_PERSIST_SPEC=""
  B2U_PERSIST_DEVICE=""

  [[ -f "$B2U_READONLY_ENV_FILE" ]] || return 0

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ ! "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=\"([^\"]*)\"$ ]]; then
      fail "Refusing to load invalid read-only config line from ${B2U_READONLY_ENV_FILE}: ${line}"
    fi

    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      B2U_READONLY_MODE | B2U_PERSIST_MOUNT | B2U_PERSIST_BLUETOOTH_DIR | B2U_PERSIST_SPEC | B2U_PERSIST_DEVICE)
        printf -v "$key" '%s' "$value"
        ;;
      *)
        fail "Refusing to load unexpected key from ${B2U_READONLY_ENV_FILE}: ${key}"
        ;;
    esac
  done <"$B2U_READONLY_ENV_FILE"
}

write_readonly_config() {
  local mode="${1:-disabled}"
  local persist_mount="${2:-$B2U_PERSIST_MOUNT_PATH}"
  local persist_bluetooth_dir="${3:-${persist_mount}/${B2U_PERSIST_BLUETOOTH_SUBDIR}}"
  local persist_spec="${4:-}"
  local persist_device="${5:-}"

  cat >"$B2U_READONLY_ENV_FILE" <<EOF
B2U_READONLY_MODE="${mode}"
B2U_PERSIST_MOUNT="${persist_mount}"
B2U_PERSIST_BLUETOOTH_DIR="${persist_bluetooth_dir}"
B2U_PERSIST_SPEC="${persist_spec}"
B2U_PERSIST_DEVICE="${persist_device}"
EOF
  chmod 0644 "$B2U_READONLY_ENV_FILE"
}

bluetooth_state_persistent() {
  local mount_source
  local persist_mount_source
  local relative_subdir

  load_readonly_config
  mountpoint -q /var/lib/bluetooth || return 1
  [[ -d "$B2U_PERSIST_BLUETOOTH_DIR" ]] || return 1
  mount_source="$(findmnt -n -o SOURCE --target /var/lib/bluetooth 2>/dev/null || true)"
  if [[ "$mount_source" == "$B2U_PERSIST_BLUETOOTH_DIR" ]]; then
    return 0
  fi

  persist_mount_source="$(findmnt -n -o SOURCE --target "$B2U_PERSIST_MOUNT" 2>/dev/null || true)"
  [[ -n "$persist_mount_source" ]] || return 1

  relative_subdir="${B2U_PERSIST_BLUETOOTH_DIR#"${B2U_PERSIST_MOUNT}"}"
  [[ "$relative_subdir" == /* ]] || relative_subdir="/${relative_subdir}"
  [[ "$mount_source" == "${persist_mount_source}[${relative_subdir}]" ]]
}

readonly_mode() {
  if root_overlay_active && bluetooth_state_persistent; then
    printf '%s\n' "persistent"
  else
    printf '%s\n' "disabled"
  fi
}

persist_mount_unit_name() {
  local mount_path="$1"

  systemd-escape --path --suffix=mount "$mount_path"
}

write_persist_mount_unit() {
  local persist_spec="$1"
  local mount_path="$2"
  local fs_type="$3"
  local unit_name

  [[ -n "$persist_spec" ]] || fail "Persistent mount spec must not be empty."
  [[ "$persist_spec" != *$'\n'* ]] || fail "Persistent mount spec must not contain newlines."
  [[ "$persist_spec" =~ ^[A-Za-z0-9_./:=-]+$ ]] || fail "Persistent mount spec contains unsupported characters: ${persist_spec}"
  unit_name="$(persist_mount_unit_name "$mount_path")"
  cat >"/etc/systemd/system/${unit_name}" <<EOF
[Unit]
Description=bluetooth_2_usb persistent storage mount
Before=local-fs.target bluetooth.service ${B2U_SERVICE_UNIT}

[Mount]
What=${persist_spec}
Where=${mount_path}
Type=${fs_type}
Options=defaults,noatime

[Install]
WantedBy=local-fs.target
EOF
  chmod 0644 "/etc/systemd/system/${unit_name}"
}

remove_persist_mount_unit() {
  local mount_path="${1:-$B2U_PERSIST_MOUNT_PATH}"
  local unit_name

  unit_name="$(persist_mount_unit_name "$mount_path")"
  rm -f "/etc/systemd/system/${unit_name}"
}

write_bluetooth_bind_mount_unit() {
  local source_dir="$1"

  mkdir -p /var/lib/bluetooth
  cat >"$B2U_BLUETOOTH_BIND_MOUNT_UNIT" <<EOF
[Unit]
Description=bluetooth_2_usb persistent Bluetooth state bind mount
After=$(persist_mount_unit_name "$(dirname "$source_dir")")
Requires=$(persist_mount_unit_name "$(dirname "$source_dir")")
Before=bluetooth.service ${B2U_SERVICE_UNIT}

[Mount]
What=${source_dir}
Where=/var/lib/bluetooth
Type=none
Options=bind

[Install]
WantedBy=local-fs.target
EOF
  chmod 0644 "$B2U_BLUETOOTH_BIND_MOUNT_UNIT"
}

remove_bluetooth_bind_mount_unit() {
  rm -f "$B2U_BLUETOOTH_BIND_MOUNT_UNIT"
}

install_bluetooth_persist_dropin() {
  mkdir -p "$B2U_BLUETOOTH_SERVICE_DROPIN_DIR"
  cat >"$B2U_BLUETOOTH_SERVICE_DROPIN" <<'EOF'
[Unit]
After=var-lib-bluetooth.mount
Requires=var-lib-bluetooth.mount
RequiresMountsFor=/var/lib/bluetooth

[Service]
EOF
  chmod 0644 "$B2U_BLUETOOTH_SERVICE_DROPIN"
}

remove_bluetooth_persist_dropin() {
  rm -f "$B2U_BLUETOOTH_SERVICE_DROPIN"
  rmdir "$B2U_BLUETOOTH_SERVICE_DROPIN_DIR" 2>/dev/null || true
}

persist_spec_from_device() {
  local device="$1"
  local uuid

  uuid="$(blkid -s UUID -o value "$device" 2>/dev/null || true)"
  [[ -n "$uuid" ]] || fail "Could not determine UUID for ${device}"
  printf '%s\n' "/dev/disk/by-uuid/${uuid}"
}
