#!/usr/bin/env bash

if [[ -n "${B2U_COMMON_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_COMMON_SH_SOURCED=1

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[1;36m'
BOLD=$'\033[1m'
NC=$'\033[0m'

readonly B2U_INSTALL_DIR="/opt/bluetooth_2_usb"
readonly B2U_SERVICE_UNIT="bluetooth_2_usb.service"
readonly B2U_LOG_DIR="/var/log/bluetooth_2_usb"
readonly B2U_ENV_FILE="/etc/default/bluetooth_2_usb"
readonly B2U_READONLY_ENV_FILE="/etc/default/bluetooth_2_usb_readonly"
readonly B2U_STATE_DIR="/var/lib/bluetooth_2_usb"
readonly B2U_MANAGED_SOURCE_FILE="${B2U_STATE_DIR}/managed_source.env"
readonly B2U_BOOT_RESTORE_DIR="${B2U_STATE_DIR}/boot_restore"
readonly B2U_BOOT_RESTORE_CONFIG="${B2U_BOOT_RESTORE_DIR}/config.txt"
readonly B2U_BOOT_RESTORE_CMDLINE="${B2U_BOOT_RESTORE_DIR}/cmdline.txt"
readonly B2U_PERSIST_MOUNT_PATH="/mnt/b2u-persist"
readonly B2U_PERSIST_BLUETOOTH_SUBDIR="bluetooth"
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
  mkdir -p "$B2U_LOG_DIR"
  logfile="${B2U_LOG_DIR}/${prefix}_$(timestamp).log"
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

capture_boot_restore_snapshot() {
  local config_file="$1"
  local cmdline_file="$2"
  mkdir -p "$B2U_BOOT_RESTORE_DIR"
  cp -a "$config_file" "$B2U_BOOT_RESTORE_CONFIG"
  cp -a "$cmdline_file" "$B2U_BOOT_RESTORE_CMDLINE"
}

restore_boot_restore_snapshot() {
  local config_file="$1"
  local cmdline_file="$2"
  [[ -f "$B2U_BOOT_RESTORE_CONFIG" ]] || fail "No managed config.txt snapshot found for boot restore."
  [[ -f "$B2U_BOOT_RESTORE_CMDLINE" ]] || fail "No managed cmdline.txt snapshot found for boot restore."
  cp -a "$B2U_BOOT_RESTORE_CONFIG" "$config_file"
  cp -a "$B2U_BOOT_RESTORE_CMDLINE" "$cmdline_file"
}

clear_boot_restore_snapshot() {
  rm -f "$B2U_BOOT_RESTORE_CONFIG" "$B2U_BOOT_RESTORE_CMDLINE"
  rmdir "$B2U_BOOT_RESTORE_DIR" 2>/dev/null || true
}

default_repo_url() {
  if git -C "$B2U_REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local remote_url
    remote_url="$(git -C "$B2U_REPO_ROOT" remote get-url origin 2>/dev/null || true)"
    if [[ -n "$remote_url" ]]; then
      printf '%s\n' "$remote_url"
      return
    fi
    printf '%s\n' "$B2U_REPO_ROOT"
  else
    printf '%s\n' "https://github.com/quaxalber/bluetooth_2_usb.git"
  fi
}

default_repo_ref() {
  local branch_name
  local tag_name

  branch_name="$(git -C "$B2U_REPO_ROOT" symbolic-ref -q --short HEAD 2>/dev/null || true)"
  if [[ -n "$branch_name" ]]; then
    printf '%s\n' "$branch_name"
    return
  fi

  tag_name="$(git -C "$B2U_REPO_ROOT" describe --tags --exact-match 2>/dev/null || true)"
  if [[ -n "$tag_name" ]]; then
    printf '%s\n' "$tag_name"
    return
  fi

  printf '%s\n' "main"
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
  if command -v modinfo >/dev/null 2>&1 && modinfo dwc2 >/dev/null 2>&1; then
    printf '%s\n' "module"
    return
  fi
  if [[ -d /sys/module/dwc2 ]]; then
    printf '%s\n' "builtin"
    return
  fi
  printf '%s\n' "unknown"
}

required_boot_modules_csv() {
  if [[ "$(dwc2_mode)" == "module" ]]; then
    printf '%s\n' "dwc2,libcomposite"
  else
    printf '%s\n' "libcomposite"
  fi
}

board_overlay_line() {
  local model="$1"
  case "$model" in
    *"Raspberry Pi 4"* | *"Raspberry Pi 5"*)
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
  require_commands python3
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

normalize_modules_load() {
  local cmdline_file="$1"
  local modules="$2"
  require_commands python3
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

install_service_unit() {
  install -m 0644 "${B2U_REPO_ROOT}/bluetooth_2_usb.service" \
    "/etc/systemd/system/${B2U_SERVICE_UNIT}"
}

activate_service_unit() {
  local was_active=0

  if systemctl is-active --quiet "${B2U_SERVICE_UNIT}"; then
    was_active=1
  fi

  systemctl enable "${B2U_SERVICE_UNIT}"
  if [[ $was_active -eq 1 ]]; then
    systemctl restart "${B2U_SERVICE_UNIT}"
  else
    systemctl start "${B2U_SERVICE_UNIT}"
  fi
}
write_default_env_file() {
  if [[ ! -f "$B2U_ENV_FILE" ]]; then
    cat >"$B2U_ENV_FILE" <<'EOF'
# Optional runtime arguments for bluetooth_2_usb.service.
BLUETOOTH_2_USB_ARGS="--auto_discover --grab_devices --interrupt_shortcut CTRL+SHIFT+F12 --hid-profile compat"
EOF
    chmod 0644 "$B2U_ENV_FILE"
  fi
}

install_cli_wrapper() {
  cat >/usr/local/bin/bluetooth_2_usb <<EOF
#!/usr/bin/env bash
exec "${B2U_INSTALL_DIR}/venv/bin/python" -m bluetooth_2_usb "\$@"
EOF
  chmod 0755 /usr/local/bin/bluetooth_2_usb
}

recreate_venv() {
  local venv_dir="$1"
  rm -rf "$venv_dir"
  python3 -m venv "$venv_dir"
}

rebuild_venv_atomically() {
  local venv_dir="$1"
  local package_dir="$2"
  local staging_dir="${venv_dir}.new"
  local backup_dir="${venv_dir}.backup.$(timestamp)"

  rm -rf "$staging_dir"
  recreate_venv "$staging_dir" || {
    rm -rf "$staging_dir"
    return 1
  }

  if ! "${staging_dir}/bin/pip" install --upgrade pip setuptools wheel; then
    rm -rf "$staging_dir"
    return 1
  fi
  if ! "${staging_dir}/bin/pip" install --upgrade "$package_dir"; then
    rm -rf "$staging_dir"
    return 1
  fi

  if [[ -e "$venv_dir" ]]; then
    mv "$venv_dir" "$backup_dir" || {
      rm -rf "$staging_dir"
      return 1
    }
  fi

  if mv "$staging_dir" "$venv_dir"; then
    rm -rf "$backup_dir"
    return 0
  fi

  rm -rf "$venv_dir" "$staging_dir"
  if [[ -e "$backup_dir" ]]; then
    mv "$backup_dir" "$venv_dir" || warn "Failed to restore ${venv_dir} from ${backup_dir}"
  fi
  return 1
}

service_installed() {
  systemctl list-unit-files --type=service 2>/dev/null | grep -Fq "${B2U_SERVICE_UNIT}"
}

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

readonly_warning_easy_mode() {
  cat <<'EOF'
Easy Mode only enables Raspberry Pi OS OverlayFS.
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
  B2U_PERSIST_MOUNT="$B2U_PERSIST_MOUNT_PATH"
  B2U_PERSIST_BLUETOOTH_DIR="${B2U_PERSIST_MOUNT_PATH}/${B2U_PERSIST_BLUETOOTH_SUBDIR}"
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
        B2U_READONLY_MODE | B2U_PERSIST_MOUNT | B2U_PERSIST_BLUETOOTH_DIR | B2U_PERSIST_SPEC | B2U_PERSIST_DEVICE)
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
  load_readonly_config
  mountpoint -q /var/lib/bluetooth || return 1
  [[ -d "$B2U_PERSIST_BLUETOOTH_DIR" ]] || return 1
  findmnt -n -o OPTIONS --target /var/lib/bluetooth 2>/dev/null | grep -qw bind || return 1
  mount_source="$(findmnt -n -o SOURCE --target /var/lib/bluetooth 2>/dev/null || true)"
  [[ "$mount_source" == "$B2U_PERSIST_BLUETOOTH_DIR" ]]
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
  local unit_name

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
  local mount_path="${1:-$B2U_PERSIST_MOUNT}"
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

resolve_latest_release_tag() {
  local repo_url="$1"
  local repo_slug
  local api_url
  local response
  local tag_name

  case "$repo_url" in
    https://github.com/*) repo_slug="${repo_url#https://github.com/}" ;;
    http://github.com/*) repo_slug="${repo_url#http://github.com/}" ;;
    git@github.com:*) repo_slug="${repo_url#git@github.com:}" ;;
    ssh://git@github.com/*) repo_slug="${repo_url#ssh://git@github.com/}" ;;
    *) return 1 ;;
  esac
  repo_slug="${repo_slug%.git}"
  [[ "$repo_slug" == */* ]] || return 1

  require_commands curl sed
  api_url="https://api.github.com/repos/${repo_slug}/releases/latest"
  response="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api_url")" || return 1
  tag_name="$(printf '%s' "$response" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  [[ -n "$tag_name" ]] || return 1
  printf '%s\n' "$tag_name"
}

load_managed_source_config() {
  B2U_MANAGED_REPO_URL=""
  B2U_MANAGED_REF_MODE=""
  B2U_MANAGED_REF=""

  [[ -f "$B2U_MANAGED_SOURCE_FILE" ]] || return 0

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "$line" ]] || continue
    if [[ ! "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=\"([^\"]*)\"$ ]]; then
      fail "Refusing to load invalid managed source line from ${B2U_MANAGED_SOURCE_FILE}: ${line}"
    fi

    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      B2U_MANAGED_REPO_URL | B2U_MANAGED_REF_MODE | B2U_MANAGED_REF)
        printf -v "$key" '%s' "$value"
        ;;
      *)
        fail "Refusing to load unexpected key from ${B2U_MANAGED_SOURCE_FILE}: ${key}"
        ;;
    esac
  done <"$B2U_MANAGED_SOURCE_FILE"
}

write_managed_source_config() {
  local repo_url="$1"
  local ref_mode="$2"
  local ref="${3:-}"

  mkdir -p "$B2U_STATE_DIR"
  cat >"$B2U_MANAGED_SOURCE_FILE" <<EOF
B2U_MANAGED_REPO_URL="${repo_url}"
B2U_MANAGED_REF_MODE="${ref_mode}"
B2U_MANAGED_REF="${ref}"
EOF
  chmod 0644 "$B2U_MANAGED_SOURCE_FILE"
}

remove_managed_source_config() {
  rm -f "$B2U_MANAGED_SOURCE_FILE"
}

checkout_ref_mode() {
  local repo_dir="$1"
  local branch_name
  local tag_name

  branch_name="$(git -C "$repo_dir" symbolic-ref -q --short HEAD 2>/dev/null || true)"
  if [[ -n "$branch_name" ]]; then
    printf '%s\n' "branch"
    return
  fi

  tag_name="$(git -C "$repo_dir" describe --tags --exact-match 2>/dev/null || true)"
  if [[ -n "$tag_name" ]]; then
    printf '%s\n' "tag"
    return
  fi

  printf '%s\n' "detached"
}

checkout_ref_name() {
  local repo_dir="$1"
  local branch_name
  local tag_name

  branch_name="$(git -C "$repo_dir" symbolic-ref -q --short HEAD 2>/dev/null || true)"
  if [[ -n "$branch_name" ]]; then
    printf '%s\n' "$branch_name"
    return
  fi

  tag_name="$(git -C "$repo_dir" describe --tags --exact-match 2>/dev/null || true)"
  if [[ -n "$tag_name" ]]; then
    printf '%s\n' "$tag_name"
    return
  fi

  git -C "$repo_dir" rev-parse --short HEAD
}

ensure_repo_remote() {
  local repo_dir="$1"
  local repo_url="$2"

  if git -C "$repo_dir" remote get-url origin >/dev/null 2>&1; then
    git -C "$repo_dir" remote set-url origin "$repo_url"
  else
    git -C "$repo_dir" remote add origin "$repo_url"
  fi
}
