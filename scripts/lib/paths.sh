#!/usr/bin/env bash

if [[ -n "${B2U_PATHS_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_PATHS_SH_SOURCED=1

readonly B2U_INSTALL_DIR="/opt/bluetooth_2_usb"
readonly B2U_SERVICE_UNIT="bluetooth_2_usb.service"
readonly B2U_LOG_DIR="/var/log/bluetooth_2_usb"
readonly B2U_STATE_DIR="/var/lib/bluetooth_2_usb"
readonly B2U_ENV_FILE="/etc/default/bluetooth_2_usb"
readonly B2U_READONLY_ENV_FILE="/etc/default/bluetooth_2_usb_readonly"
readonly B2U_OPTIMIZE_STATE_FILE="${B2U_STATE_DIR}/optimize_pi_boot_state.env"
readonly B2U_PERSIST_MOUNT_PATH="/mnt/b2u-persist"
readonly B2U_PERSIST_BLUETOOTH_SUBDIR="bluetooth"
readonly B2U_BLUETOOTH_BIND_MOUNT_UNIT="/etc/systemd/system/var-lib-bluetooth.mount"
readonly B2U_BLUETOOTH_SERVICE_DROPIN_DIR="/etc/systemd/system/bluetooth.service.d"
readonly B2U_BLUETOOTH_SERVICE_DROPIN="${B2U_BLUETOOTH_SERVICE_DROPIN_DIR}/bluetooth_2_usb_persist.conf"

B2U_PATHS_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B2U_REPO_ROOT="$(cd -- "${B2U_PATHS_DIR}/../.." && pwd)"
