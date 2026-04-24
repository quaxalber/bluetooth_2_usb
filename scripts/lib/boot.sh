#!/usr/bin/env bash

if [[ -n "${B2U_BOOT_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_BOOT_SH_SOURCED=1

_b2u_boot_dir="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./paths.sh
source "${_b2u_boot_dir}/paths.sh"
# shellcheck source=./common.sh
source "${_b2u_boot_dir}/common.sh"
unset _b2u_boot_dir

detect_boot_dir() {
  if [[ -d /boot/firmware ]]; then
    printf '%s\n' "/boot/firmware"
  else
    printf '%s\n' "/boot"
  fi
}

default_kernel_image() {
  local model arm_64bit

  if ! model="$(current_pi_model)"; then
    model=""
  fi
  arm_64bit="$(effective_arm_64bit)"

  case "$model" in
    *"Raspberry Pi 500"* | *"Raspberry Pi 5"* | *"Compute Module 5"*)
      printf '%s\n' "kernel_2712.img"
      ;;
    *"Raspberry Pi 400"* | *"Raspberry Pi 4"* | *"Compute Module 4"*)
      if [[ "$arm_64bit" == "1" ]]; then
        printf '%s\n' "kernel8.img"
      else
        printf '%s\n' "kernel7l.img"
      fi
      ;;
    *"Raspberry Pi 2"* | *"Raspberry Pi 3"* | *"Raspberry Pi Zero 2"* | *"Compute Module 3"*)
      if [[ "$arm_64bit" == "1" ]]; then
        printf '%s\n' "kernel8.img"
      else
        printf '%s\n' "kernel7.img"
      fi
      ;;
    *)
      case "$(uname -m)" in
        aarch64)
          printf '%s\n' "kernel8.img"
          ;;
        armv7l)
          if grep -q '^Features.*\blpae\b' /proc/cpuinfo 2>/dev/null; then
            printf '%s\n' "kernel7l.img"
          else
            printf '%s\n' "kernel7.img"
          fi
          ;;
        *)
          printf '%s\n' "kernel.img"
          ;;
      esac
      ;;
  esac
}

boot_config_path() {
  printf '%s/config.txt\n' "$(detect_boot_dir)"
}

boot_cmdline_path() {
  printf '%s/cmdline.txt\n' "$(detect_boot_dir)"
}

boot_config_model_filters() {
  local model=""

  model="$(current_pi_model 2>/dev/null || true)"

  case "$model" in
    *"Raspberry Pi 500+"* | *"Raspberry Pi 500"*)
      printf '%s\n' "pi5" "pi500"
      ;;
    *"Raspberry Pi 5"*)
      printf '%s\n' "pi5"
      ;;
    *"Compute Module 5"*)
      printf '%s\n' "pi5" "cm5"
      ;;
    *"Raspberry Pi 400"*)
      printf '%s\n' "pi4" "pi400"
      ;;
    *"Compute Module 4S"*)
      printf '%s\n' "pi4" "cm4s"
      ;;
    *"Compute Module 4"*)
      printf '%s\n' "pi4" "cm4"
      ;;
    *"Raspberry Pi 4"*)
      printf '%s\n' "pi4"
      ;;
    *"Compute Module 3 Plus"* | *"Compute Module 3+"*)
      printf '%s\n' "pi3" "pi3+" "cm3+"
      ;;
    *"Compute Module 3"*)
      printf '%s\n' "pi3" "cm3"
      ;;
    *"Raspberry Pi 3 Model A Plus"* | *"Raspberry Pi 3 Model B Plus"*)
      printf '%s\n' "pi3" "pi3+"
      ;;
    *"Raspberry Pi 3"*)
      printf '%s\n' "pi3"
      ;;
    *"Raspberry Pi Zero 2"*)
      printf '%s\n' "pi0" "pi0w" "pi02"
      ;;
    *"Raspberry Pi Zero W"*)
      printf '%s\n' "pi0" "pi0w"
      ;;
    *"Raspberry Pi Zero"*)
      printf '%s\n' "pi0"
      ;;
    *"Raspberry Pi 2"*)
      printf '%s\n' "pi2"
      ;;
    *"Compute Module 1"*)
      printf '%s\n' "pi1" "cm1"
      ;;
    *"Compute Module 0"*)
      printf '%s\n' "pi0" "cm0"
      ;;
    *"Raspberry Pi 1"*)
      printf '%s\n' "pi1"
      ;;
  esac
}

boot_config_assignment_value() {
  local key="$1"
  local config_file="${2:-$(boot_config_path)}"
  local -a model_filters=()

  if (($# > 2)); then
    model_filters=("${@:3}")
  else
    mapfile -t model_filters < <(boot_config_model_filters)
  fi

  [[ -f "$config_file" ]] || return 0
  python3 - "$config_file" "$key" "${model_filters[@]}" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
target_key = sys.argv[2]
allowed_sections = {"", "all"}
allowed_sections.update(section.lower() for section in sys.argv[3:] if section.strip())
value = ""
current_section = ""

for raw_line in config_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.split("#", 1)[0].strip()
    if not line:
        continue
    if line.startswith("[") and line.endswith("]"):
        current_section = line[1:-1].strip().lower()
        continue
    if "=" not in line or current_section not in allowed_sections:
        continue
    key, current_value = line.split("=", 1)
    if key.strip() == target_key:
        value = current_value.strip()

if value:
    print(value)
PY
}

configured_kernel_image() {
  local value

  value="$(boot_config_assignment_value "kernel")"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
  else
    default_kernel_image
  fi
}

# shellcheck disable=SC2120  # Library helper accepts optional config path and model filters.
configured_initramfs_file() {
  local config_file="${1:-$(boot_config_path)}"
  local -a model_filters=()

  if (($# > 1)); then
    model_filters=("${@:2}")
  else
    mapfile -t model_filters < <(boot_config_model_filters)
  fi

  [[ -f "$config_file" ]] || return 0
  python3 - "$config_file" "${model_filters[@]}" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
allowed_sections = {"", "all"}
allowed_sections.update(section.lower() for section in sys.argv[2:] if section.strip())
value = ""
current_section = ""

for raw_line in config_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.split("#", 1)[0].strip()
    if not line:
        continue
    if line.startswith("[") and line.endswith("]"):
        current_section = line[1:-1].strip().lower()
        continue
    if current_section not in allowed_sections:
        continue
    if not line.startswith("initramfs "):
        continue
    parts = line.split()
    if len(parts) >= 2:
        value = parts[1]

if value:
    print(value)
PY
}

auto_initramfs_enabled() {
  [[ "$(boot_config_assignment_value "auto_initramfs")" == "1" ]]
}

effective_arm_64bit() {
  local configured_value

  configured_value="$(boot_config_assignment_value "arm_64bit")"
  if [[ "$configured_value" == "1" ]]; then
    printf '%s\n' "1"
  elif [[ "$configured_value" == "0" ]]; then
    printf '%s\n' "0"
  elif [[ "$(uname -m)" == "aarch64" ]]; then
    printf '%s\n' "1"
  else
    printf '%s\n' "0"
  fi
}

# shellcheck disable=SC2120  # Library helper forwards optional model filters.
expected_auto_initramfs_name() {
  local kernel_image="${1:-$(configured_kernel_image)}"
  local base_name

  base_name="${kernel_image##*/}"
  base_name="${base_name%.*}"
  if [[ "$base_name" == kernel* ]]; then
    printf '%s\n' "initramfs${base_name#kernel}"
  fi
}

# shellcheck disable=SC2120  # Library helper forwards optional config path and model filters.
expected_boot_initramfs_file() {
  local explicit_initramfs

  explicit_initramfs="$(configured_initramfs_file "$@")"
  if [[ -n "$explicit_initramfs" ]]; then
    printf '%s\n' "$explicit_initramfs"
    return
  fi

  if auto_initramfs_enabled; then
    expected_auto_initramfs_name
  fi
}

# shellcheck disable=SC2120  # Library helper accepts an explicit target file or forwards optional initramfs lookup args.
boot_initramfs_target_path() {
  local target_file="${1:-}"

  if [[ -n "$target_file" ]]; then
    shift
  fi
  if [[ -z "$target_file" ]]; then
    target_file="$(expected_boot_initramfs_file "$@")"
  fi

  [[ -n "$target_file" ]] || return 1
  if [[ "$target_file" == /* || "$target_file" == *"/"* || "$target_file" == *".."* ]]; then
    printf '%s\n' "Unsafe initramfs target file in $(boot_config_path): ${target_file}" >&2
    return 1
  fi
  printf '%s/%s\n' "$(detect_boot_dir)" "$target_file"
}

current_kernel_release() {
  uname -r
}

# The exit status reflects whether detection succeeded; the emitted value is the
# overlay state ("yes", "no", or "unknown"), not a boolean predicate.
root_overlay_state() {
  local root_fstype

  if ! root_fstype="$(current_root_filesystem_type)"; then
    printf '%s\n' "unknown"
    return 1
  fi

  if [[ "$root_fstype" == "overlay" ]]; then
    printf '%s\n' "yes"
  else
    printf '%s\n' "no"
  fi
}

versioned_initrd_candidates() {
  local kernel_release="${1:-$(current_kernel_release)}"
  local boot_dir

  boot_dir="$(detect_boot_dir)"
  printf '%s\n' "/boot/initrd.img-${kernel_release}"
  if [[ "$boot_dir" != "/boot" ]]; then
    printf '%s\n' "${boot_dir}/initrd.img-${kernel_release}"
  fi
}

find_versioned_initramfs_image() {
  local kernel_release="${1:-$(current_kernel_release)}"
  local candidate

  while IFS= read -r candidate; do
    if [[ -s "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(versioned_initrd_candidates "$kernel_release")

  return 1
}

ensure_initramfs_tools_ready() {
  require_commands install python3 update-initramfs
  command -v mkinitramfs >/dev/null 2>&1 || fail "mkinitramfs is missing. Install initramfs-tools before enabling read-only mode."
}

ensure_kernel_artifacts_present_for_initramfs() {
  local kernel_release="${1:-$(current_kernel_release)}"

  [[ -d "/lib/modules/${kernel_release}" ]] || fail "Kernel modules for ${kernel_release} are missing at /lib/modules/${kernel_release}."
  if [[ ! -f "/boot/config-${kernel_release}" && ! -f /proc/config.gz ]]; then
    fail "Kernel configuration for ${kernel_release} is unavailable. Expected /boot/config-${kernel_release} or /proc/config.gz."
  fi
}

run_update_initramfs() {
  local action="$1"
  local kernel_release="$2"
  local output=""
  local status=0
  local filtered_output=""

  output="$(update-initramfs "$action" -k "$kernel_release" 2>&1)" || status=$?
  filtered_output="$(
    printf '%s\n' "$output" | sed -E \
      -e '/^WARNING:.*Unsupported initramfs version/d' \
      -e '/^NOTE:.*Manual boot configuration/d'
  )"

  if [[ -n "$filtered_output" ]]; then
    printf '%s\n' "$filtered_output" >&2
  fi

  return "$status"
}

build_or_refresh_initramfs_for_running_kernel() {
  local kernel_release="${1:-$(current_kernel_release)}"
  local target_path="${2:-}"
  local existing_image_path=""
  local image_path

  existing_image_path="$(find_versioned_initramfs_image "$kernel_release" || true)"
  if [[ -n "$existing_image_path" ]]; then
    if [[ -n "$target_path" && "$existing_image_path" == "$target_path" && -f "$target_path" ]]; then
      backup_file "$target_path" || fail "Failed to back up ${target_path}"
    fi
    run_update_initramfs "-u" "$kernel_release" || run_update_initramfs "-c" "$kernel_release" || fail "update-initramfs failed for kernel ${kernel_release}."
  else
    run_update_initramfs "-c" "$kernel_release" || fail "update-initramfs failed for kernel ${kernel_release}."
  fi

  image_path="$(find_versioned_initramfs_image "$kernel_release" || true)"
  [[ -n "$image_path" ]] || fail "update-initramfs completed, but no initramfs image was found for kernel ${kernel_release}."
  printf '%s\n' "$image_path"
}

install_expected_boot_initramfs() {
  local source_image="$1"
  local target_path="$2"

  [[ -s "$source_image" ]] || fail "Initramfs source image is missing or empty: ${source_image}"
  [[ -n "$target_path" ]] || fail "Boot initramfs target path must not be empty."
  mkdir -p "$(dirname "$target_path")"
  if [[ "$source_image" != "$target_path" ]]; then
    if [[ -f "$target_path" ]]; then
      backup_file "$target_path" || fail "Failed to back up ${target_path}"
    fi
    install -m 0644 "$source_image" "$target_path" || fail "Failed to install ${target_path}"
  fi
  [[ -s "$target_path" ]] || fail "Boot initramfs target is missing or empty after install: ${target_path}"
  printf '%s\n' "$target_path"
}

ensure_bootable_initramfs_for_current_kernel() {
  local kernel_release
  local target_path
  local image_path
  local overlay_state

  kernel_release="$(current_kernel_release)"
  target_path="$(boot_initramfs_target_path || true)"
  [[ -n "$target_path" ]] || fail "Boot initramfs target is not configured. Set auto_initramfs=1 or add an initramfs entry to $(boot_config_path)."
  overlay_state="$(root_overlay_state || true)"
  if [[ "$overlay_state" != "yes" && "$overlay_state" != "no" ]]; then
    fail "Unable to determine live root overlay state; aborting initramfs operations."
  fi
  if [[ "$overlay_state" == "yes" ]]; then
    [[ -s "$target_path" ]] || fail "Boot initramfs target ${target_path} is missing while the live root overlay is active. Disable read-only mode before rebuilding initramfs."
    printf '%s\n' "$target_path"
    return 0
  fi
  ensure_initramfs_tools_ready
  ensure_kernel_artifacts_present_for_initramfs "$kernel_release"
  image_path="$(build_or_refresh_initramfs_for_running_kernel "$kernel_release" "$target_path")"
  install_expected_boot_initramfs "$image_path" "$target_path" >/dev/null
  printf '%s\n' "$target_path"
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
  # Last-resort heuristic only: /sys/module/dwc2 can exist for both built-in and
  # loadable-module cases, so this branch may misclassify when earlier kernel
  # config checks could not determine the mode.
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

current_pi_model() {
  local model_file="/proc/device-tree/model"

  [[ -r "$model_file" ]] || return 1
  tr -d '\0' <"$model_file"
}

current_root_filesystem_type() {
  local root_fstype

  root_fstype="$(findmnt -n -o FSTYPE --target / 2>/dev/null)" || return 1
  [[ -n "$root_fstype" ]] || return 1
  printf '%s\n' "$root_fstype"
}

expected_dwc2_overlay_line() {
  local model

  model="$(current_pi_model)" || fail "Could not determine Raspberry Pi model from /proc/device-tree/model."
  board_overlay_line "$model"
}

normalize_dwc2_overlay() {
  local config_file="$1"
  local overlay_line="$2"

  [[ -f "$config_file" ]] || fail "Boot config file not found: ${config_file}"
  [[ -w "$config_file" ]] || fail "Boot config file is not writable: ${config_file}"
  backup_file "$config_file" || fail "Failed to back up ${config_file}"
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

  [[ -f "$cmdline_file" ]] || fail "Boot cmdline file not found: ${cmdline_file}"
  [[ -w "$cmdline_file" ]] || fail "Boot cmdline file is not writable: ${cmdline_file}"
  backup_file "$cmdline_file" || fail "Failed to back up ${cmdline_file}"
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
        existing.extend(value for value in token.split("=", 1)[1].split(",") if value)

merged = []
for value in [*existing, *modules.split(",")]:
    if value and value not in merged:
        merged.append(value)

tokens = [token for token in tokens if not token.startswith("modules-load=")]
tokens.append("modules-load=" + ",".join(merged))
cmdline_path.write_text(" ".join(tokens) + "\n", encoding="utf-8")
PY
}
