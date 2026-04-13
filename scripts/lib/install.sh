#!/usr/bin/env bash

if [[ -n "${B2U_INSTALL_LIB_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_INSTALL_LIB_SH_SOURCED=1

_b2u_install_lib_dir="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./paths.sh
source "${_b2u_install_lib_dir}/paths.sh"
# shellcheck source=./common.sh
source "${_b2u_install_lib_dir}/common.sh"
unset _b2u_install_lib_dir

install_service_unit() {
  install -m 0644 "${B2U_REPO_ROOT}/bluetooth_2_usb.service" "/etc/systemd/system/${B2U_SERVICE_UNIT}"
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
# Structured runtime configuration for bluetooth_2_usb.service.
B2U_AUTO_DISCOVER=1
B2U_GRAB_DEVICES=1
B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12
B2U_HID_PROFILE=boot_keyboard
B2U_LOG_TO_FILE=0
B2U_LOG_PATH=/var/log/bluetooth_2_usb/bluetooth_2_usb.log
B2U_DEBUG=0
B2U_DEVICE_IDS=
B2U_UDC_PATH=
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

repair_venv_shebangs() {
  local venv_dir="$1"
  local staging_dir="$2"
  local file=""
  local first_line=""
  local rewritten_line=""
  local tmp=""

  for file in "${venv_dir}"/bin/*; do
    [[ -f "$file" ]] || continue
    IFS= read -r first_line <"$file" || true
    [[ "$first_line" == "#!${staging_dir}"* ]] || continue

    rewritten_line="#!${venv_dir}${first_line#\#!"${staging_dir}"}"
    tmp="${file}.tmp.$$"
    {
      printf '%s\n' "$rewritten_line"
      tail -n +2 "$file" || true
    } >"$tmp"
    chmod --reference="$file" "$tmp"
    mv "$tmp" "$file"
  done
}

rebuild_venv_atomically() {
  local venv_dir="$1"
  local package_dir="$2"
  local staging_dir="${venv_dir}.new"
  local backup_dir=""
  local backup_path=""

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
    backup_dir="${venv_dir}.bak.$(timestamp)"
    mv "$venv_dir" "$backup_dir" || {
      rm -rf "$staging_dir"
      return 1
    }
  fi

  if mv "$staging_dir" "$venv_dir"; then
    repair_venv_shebangs "$venv_dir" "$staging_dir"
    if [[ -n "$backup_dir" ]]; then
      info "Previous virtual environment backed up to ${backup_dir}"
      for backup_path in "${venv_dir}".bak.*; do
        [[ -e "$backup_path" ]] || break
        [[ "$backup_path" == "$backup_dir" ]] && continue
        rm -rf "$backup_path"
      done
    fi
    return 0
  fi

  warn "Failed to activate the new virtual environment."
  if [[ -n "$backup_dir" ]]; then
    warn "Previous virtual environment remains available at ${backup_dir}."
  fi
  return 1
}

service_installed() {
  systemctl list-unit-files --type=service 2>/dev/null | grep -Fq "${B2U_SERVICE_UNIT}"
}
