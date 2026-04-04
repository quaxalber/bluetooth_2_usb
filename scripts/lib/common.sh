#!/usr/bin/env bash

if [[ -n "${B2U_COMMON_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_COMMON_SH_SOURCED=1

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'
BOLD=$'\033[1m'
NC=$'\033[0m'

readonly B2U_DEFAULT_INSTALL_DIR="/opt/bluetooth_2_usb"
readonly B2U_DEFAULT_SERVICE_NAME="bluetooth_2_usb"
readonly B2U_DEFAULT_LOG_DIR="/var/log/bluetooth_2_usb"
readonly B2U_DEFAULT_ENV_FILE="/etc/default/bluetooth_2_usb"
readonly B2U_READONLY_ENV_FILE="/etc/default/bluetooth_2_usb_readonly"
readonly B2U_DEFAULT_PERSIST_MOUNT="/mnt/b2u-persist"
readonly B2U_DEFAULT_PERSIST_BLUETOOTH_SUBDIR="bluetooth"
readonly B2U_BLUETOOTH_BIND_MOUNT_UNIT="/etc/systemd/system/var-lib-bluetooth.mount"
readonly B2U_BLUETOOTH_SERVICE_DROPIN_DIR="/etc/systemd/system/bluetooth.service.d"
readonly B2U_BLUETOOTH_SERVICE_DROPIN="${B2U_BLUETOOTH_SERVICE_DROPIN_DIR}/bluetooth_2_usb_persist.conf"

B2U_COMMON_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B2U_REPO_ROOT="$(cd -- "${B2U_COMMON_DIR}/../.." && pwd)"

timestamp() {
  date +%Y%m%d_%H%M%S
}

info() {
  printf "${BLUE}ℹ %s${NC}\n" "$*"
}

ok() {
  printf "${GREEN}✓ %s${NC}\n" "$*"
}

warn() {
  printf "${YELLOW}⚠ %s${NC}\n" "$*"
}

fail() {
  printf "${RED}✖ %s${NC}\n" "$1" >&2
  exit "${2:-1}"
}

require_value() {
  local opt="$1"
  [[ $# -ge 2 && -n "${2:-}" && "${2:-}" != -* ]] || fail "Missing value for ${opt}"
}

ensure_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || fail "Run this script as root."
}

require_commands() {
  local missing=0
  local cmd
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      warn "Missing command: $cmd"
      missing=1
    fi
  done
  [[ $missing -eq 0 ]] || fail "Install the missing commands and retry."
}

prepare_log() {
  local prefix="$1"
  local logfile
  mkdir -p "$B2U_DEFAULT_LOG_DIR"
  logfile="${B2U_DEFAULT_LOG_DIR}/${prefix}_$(timestamp).log"
  exec > >(tee -a "$logfile") 2>&1
  info "Logging to $logfile"
}

detect_boot_dir() {
  if [[ -d /boot/firmware ]]; then
    printf '%s\n' "/boot/firmware"
  else
    printf '%s\n' "/boot"
  fi
}

boot_config_path() {
  printf '%s/config.txt\n' "$(detect_boot_dir)"
}

boot_cmdline_path() {
  printf '%s/cmdline.txt\n' "$(detect_boot_dir)"
}

backup_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  cp -a "$file" "${file}.bak.$(timestamp)"
}

source_repo_root() {
  printf '%s\n' "${B2U_SOURCE_REPO:-$B2U_REPO_ROOT}"
}

default_repo_url() {
  local repo_root
  repo_root="$(source_repo_root)"
  if git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local remote_url
    remote_url="$(git -C "$repo_root" remote get-url origin 2>/dev/null || true)"
    if [[ -n "$remote_url" ]]; then
      printf '%s\n' "$remote_url"
      return
    fi
    printf '%s\n' "$repo_root"
  else
    printf '%s\n' "https://github.com/quaxalber/bluetooth_2_usb.git"
  fi
}

default_repo_branch() {
  local repo_root
  repo_root="$(source_repo_root)"
  if git -C "$repo_root" rev-parse --abbrev-ref HEAD >/dev/null 2>&1; then
    git -C "$repo_root" rev-parse --abbrev-ref HEAD
  else
    printf '%s\n' "main"
  fi
}

kernel_config_snippet() {
  local kernel_config
  kernel_config="/boot/config-$(uname -r)"
  if [[ -f "$kernel_config" ]]; then
    grep -E '^(CONFIG_USB_DWC2|CONFIG_USB_LIBCOMPOSITE)=' "$kernel_config" || true
    return
  fi

  if [[ -f /proc/config.gz ]]; then
    zcat /proc/config.gz 2>/dev/null | grep -E '^(CONFIG_USB_DWC2|CONFIG_USB_LIBCOMPOSITE)=' || true
  fi
}

dwc2_mode() {
  local snippet
  snippet="$(kernel_config_snippet)"
  if grep -q '^CONFIG_USB_DWC2=y' <<<"$snippet"; then
    printf '%s\n' "builtin"
    return
  fi
  if grep -q '^CONFIG_USB_DWC2=m' <<<"$snippet"; then
    printf '%s\n' "module"
    return
  fi
  printf '%s\n' "unknown"
}

board_overlay_line() {
  local model="$1"
  case "$model" in
    *"Raspberry Pi 4"*|*"Raspberry Pi 5"*)
      printf '%s\n' "dtoverlay=dwc2,dr_mode=peripheral"
      ;;
    *)
      printf '%s\n' "dtoverlay=dwc2"
      ;;
  esac
}

normalize_dwc2_overlay() {
  local config_file="$1"
  local overlay_line="$2"
  python3 - "$config_file" "$overlay_line" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
overlay_line = sys.argv[2]
lines = config_path.read_text(encoding="utf-8").splitlines()
filtered = [line for line in lines if not line.lstrip().startswith("dtoverlay=dwc2")]

inserted = False
result = []
for line in filtered:
    result.append(line)
    if not inserted and line.strip() == "[all]":
        result.append(overlay_line)
        inserted = True

if not inserted:
    if result and result[-1] != "":
        result.append("")
    result.extend(["[all]", overlay_line])

config_path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY
}

remove_dwc2_overlay() {
  local config_file="$1"
  python3 - "$config_file" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
lines = config_path.read_text(encoding="utf-8").splitlines()
filtered = [line for line in lines if not line.lstrip().startswith("dtoverlay=dwc2")]
config_path.write_text("\n".join(filtered).rstrip() + "\n", encoding="utf-8")
PY
}

normalize_modules_load() {
  local cmdline_file="$1"
  local modules="$2"
  python3 - "$cmdline_file" "$modules" <<'PY'
from pathlib import Path
import sys

cmdline_path = Path(sys.argv[1])
modules = sys.argv[2]
tokens = cmdline_path.read_text(encoding="utf-8").strip().split()
existing = []
for token in tokens:
    if token.startswith("modules-load="):
        existing.extend(
            value for value in token.split("=", 1)[1].split(",") if value
        )

merged = []
for value in [*existing, *modules.split(",")]:
    if value and value not in merged:
        merged.append(value)

tokens = [token for token in tokens if not token.startswith("modules-load=")]
tokens.append("modules-load=" + ",".join(merged))
cmdline_path.write_text(" ".join(tokens) + "\n", encoding="utf-8")
PY
}

remove_modules_load_entries() {
  local cmdline_file="$1"
  python3 - "$cmdline_file" <<'PY'
from pathlib import Path
import sys

cmdline_path = Path(sys.argv[1])
tokens = cmdline_path.read_text(encoding="utf-8").strip().split()
updated = []
for token in tokens:
    if not token.startswith("modules-load="):
        updated.append(token)
        continue
    values = [value for value in token.split("=", 1)[1].split(",") if value and value not in {"dwc2", "libcomposite"}]
    if values:
        updated.append("modules-load=" + ",".join(values))
cmdline_path.write_text(" ".join(updated) + "\n", encoding="utf-8")
PY
}

install_service_unit() {
  local install_dir="$1"
  local service_name="${2:-$B2U_DEFAULT_SERVICE_NAME}"
  local target="/etc/systemd/system/${service_name}.service"
  local escaped_install_dir
  escaped_install_dir="$(printf '%s' "$install_dir" | sed 's/[\\&|]/\\&/g')"
  sed "s|@INSTALL_DIR@|${escaped_install_dir}|g" "${B2U_REPO_ROOT}/bluetooth_2_usb.service" >"$target"
  chmod 0644 "$target"
}

write_default_env_file() {
  local env_file="${1:-$B2U_DEFAULT_ENV_FILE}"
  if [[ ! -f "$env_file" ]]; then
    cat >"$env_file" <<'EOF'
# Optional runtime arguments for bluetooth_2_usb.service.
BLUETOOTH_2_USB_ARGS="--auto_discover --grab_devices --interrupt_shortcut CTRL+SHIFT+F12 --hid-profile compat"
EOF
    chmod 0644 "$env_file"
  fi
}

install_cli_wrapper() {
  local install_dir="$1"
  cat >/usr/local/bin/bluetooth_2_usb <<EOF
#!/usr/bin/env bash
exec "${install_dir}/venv/bin/python" -m bluetooth_2_usb "\$@"
EOF
  chmod 0755 /usr/local/bin/bluetooth_2_usb
}

recreate_venv() {
  local venv_dir="$1"
  rm -rf "$venv_dir"
  python3 -m venv "$venv_dir"
}

service_installed() {
  local service_name="${1:-$B2U_DEFAULT_SERVICE_NAME}"
  systemctl list-unit-files --type=service 2>/dev/null | grep -Fq "${service_name}.service"
}

overlay_status() {
  if ! command -v raspi-config >/dev/null 2>&1; then
    printf '%s\n' "unknown"
    return
  fi
  if raspi-config nonint get_overlay_now >/dev/null 2>&1; then
    printf '%s\n' "enabled"
  else
    printf '%s\n' "disabled"
  fi
}

snapshot_readonly_state() {
  local boot_dir snapshot_dir
  boot_dir="$(detect_boot_dir)"
  snapshot_dir="${boot_dir}/bluetooth_2_usb/readonly_snapshot"
  mkdir -p "$snapshot_dir"
  if [[ -f /etc/machine-id ]]; then
    cp -a /etc/machine-id "${snapshot_dir}/machine-id"
  fi
  if [[ -d /var/lib/bluetooth ]]; then
    rm -rf "${snapshot_dir}/bluetooth"
    cp -a /var/lib/bluetooth "${snapshot_dir}/bluetooth"
  fi
}

readonly_warning_easy_mode() {
  cat <<'EOF'
Easy Mode only enables Raspberry Pi OS OverlayFS and stores recovery snapshots on /boot.
Bluetooth pairing persistence is best effort only in this mode.
Use the persistent mode if you need stable Bluetooth identity and pairings across reboots.
EOF
}

machine_id_valid() {
  [[ -f /etc/machine-id ]] || return 1
  grep -Eq '^[0-9a-f]{32}$' /etc/machine-id
}

load_readonly_config() {
  B2U_READONLY_MODE="disabled"
  B2U_PERSIST_MOUNT="$B2U_DEFAULT_PERSIST_MOUNT"
  B2U_PERSIST_BLUETOOTH_DIR="${B2U_DEFAULT_PERSIST_MOUNT}/${B2U_DEFAULT_PERSIST_BLUETOOTH_SUBDIR}"
  B2U_PERSIST_SPEC=""
  B2U_PERSIST_DEVICE=""
  if [[ -f "$B2U_READONLY_ENV_FILE" ]]; then
    local line key value
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ -n "$line" ]] || continue
      if [[ ! "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=\"([^\"]*)\"$ ]]; then
        fail "Refusing to load invalid read-only config line from ${B2U_READONLY_ENV_FILE}: ${line}"
      fi

      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"

      case "$key" in
        B2U_READONLY_MODE|B2U_PERSIST_MOUNT|B2U_PERSIST_BLUETOOTH_DIR|B2U_PERSIST_SPEC|B2U_PERSIST_DEVICE)
          printf -v "$key" '%s' "$value"
          ;;
        *)
          fail "Refusing to load unexpected key from ${B2U_READONLY_ENV_FILE}: ${key}"
          ;;
      esac
    done <"$B2U_READONLY_ENV_FILE"
  fi
  return 0
}

write_readonly_config() {
  local mode="${1:-disabled}"
  local persist_mount="${2:-$B2U_DEFAULT_PERSIST_MOUNT}"
  local persist_bluetooth_dir="${3:-${persist_mount}/${B2U_DEFAULT_PERSIST_BLUETOOTH_SUBDIR}}"
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
  load_readonly_config
  mountpoint -q /var/lib/bluetooth || return 1
  [[ -d "$B2U_PERSIST_BLUETOOTH_DIR" ]] || return 1
  findmnt -n -o OPTIONS --target /var/lib/bluetooth 2>/dev/null | grep -qw bind
}

readonly_mode() {
  if [[ "$(overlay_status)" != "enabled" ]]; then
    printf '%s\n' "disabled"
    return
  fi

  if bluetooth_state_persistent; then
    printf '%s\n' "persistent"
  else
    printf '%s\n' "easy"
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
  local service_name="${4:-$B2U_DEFAULT_SERVICE_NAME}"
  local unit_name

  unit_name="$(persist_mount_unit_name "$mount_path")"
  cat >"/etc/systemd/system/${unit_name}" <<EOF
[Unit]
Description=bluetooth_2_usb persistent storage mount
Before=local-fs.target bluetooth.service ${service_name}.service

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
  local mount_path="${1:-$B2U_PERSIST_MOUNT}"
  local unit_name
  unit_name="$(persist_mount_unit_name "$mount_path")"
  rm -f "/etc/systemd/system/${unit_name}"
}

write_bluetooth_bind_mount_unit() {
  local source_dir="$1"
  local service_name="${2:-$B2U_DEFAULT_SERVICE_NAME}"
  mkdir -p /var/lib/bluetooth
  cat >"$B2U_BLUETOOTH_BIND_MOUNT_UNIT" <<EOF
[Unit]
Description=bluetooth_2_usb persistent Bluetooth state bind mount
After=$(persist_mount_unit_name "$(dirname "$source_dir")")
Requires=$(persist_mount_unit_name "$(dirname "$source_dir")")
Before=bluetooth.service ${service_name}.service

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

[Service]
RequiresMountsFor=/var/lib/bluetooth
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
