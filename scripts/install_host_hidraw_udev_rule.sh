#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RULE_SRC="${REPO_ROOT}/udev/70-bluetooth_2_usb_hidraw.rules"
RULE_DST="/etc/udev/rules.d/70-bluetooth_2_usb_hidraw.rules"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
  cat <<EOF
Usage: sudo ./scripts/install_host_hidraw_udev_rule.sh

Install the host-side udev rule that grants access to the Bluetooth-2-USB
gadget hidraw nodes.
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

ensure_root

[[ -f "${RULE_SRC}" ]] || fail "Rule source not found: ${RULE_SRC}"

install -m 0644 "${RULE_SRC}" "${RULE_DST}"
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw

ok "Installed udev rule: ${RULE_DST}"
info "Reconnect the Pi gadget if the hidraw node permissions do not update immediately."
