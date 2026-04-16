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

boot_config_path() {
  printf '%s/config.txt\n' "$(detect_boot_dir)"
}

boot_cmdline_path() {
  printf '%s/cmdline.txt\n' "$(detect_boot_dir)"
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

kernel_modules_builtin_path() {
  local modules_builtin

  modules_builtin="/lib/modules/$(uname -r)/modules.builtin"
  if [[ -f "$modules_builtin" ]]; then
    printf '%s\n' "$modules_builtin"
  fi
}

dwc2_mode() {
  local snippet
  local modules_builtin

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
  modules_builtin="$(kernel_modules_builtin_path)"
  if [[ -n "$modules_builtin" ]] && grep -q '/dwc2\.ko$' "$modules_builtin"; then
    printf '%s\n' "builtin"
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
  tr -d '\0' </proc/device-tree/model 2>/dev/null || true
}

expected_dwc2_overlay_line() {
  board_overlay_line "$(current_pi_model)"
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
