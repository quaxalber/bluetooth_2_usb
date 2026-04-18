#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${SCRIPTS_DIR}/.." && pwd)"
RULE_SRC="${REPO_ROOT}/udev/70-bluetooth_2_usb_hidapi.rules"
RULE_DST="/etc/udev/rules.d/70-bluetooth_2_usb_hidapi.rules"
VENDOR_ID="1d6b"
PRODUCT_ID="0104"
# shellcheck source=../lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"

usage() {
  cat <<EOF
Usage: sudo ./scripts/host/install_host_hidapi_udev_rule.sh

Install the Linux host-side udev rule that grants hidapi write access to the
Bluetooth-2-USB gadget USB device nodes.
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

ensure_root

if [[ ! -f "${RULE_SRC}" ]]; then
  fail "Rule source not found: ${RULE_SRC}"
fi

if ! getent group input >/dev/null 2>&1; then
  fail "The 'input' group does not exist on this host."
fi

install -m 0644 "${RULE_SRC}" "${RULE_DST}"
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --attr-match=idVendor="${VENDOR_ID}" --attr-match=idProduct="${PRODUCT_ID}"

ok "Installed udev rule: ${RULE_DST}"
info "Reconnect the Pi gadget or replug the OTG cable if the USB device permissions do not update immediately."
