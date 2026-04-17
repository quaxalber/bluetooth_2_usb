#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

HOST=""
HOST_BASE=""
HOST_LOCAL=""
HOST_ALIASES=""
PI_USER="${USER:-user}"
LINK_LOCAL=""
INTERFACE=""
TIMEOUT_SEC=5

usage() {
  cat <<EOF
Usage: ./scripts/check_pi_connectivity.sh --host HOST [options]

Workstation-side Raspberry Pi connectivity probe for recurring SSH, mDNS,
link-local IPv6, and NetworkManager-related reachability issues.

Options:
  --host HOST               Pi hostname or SSH alias to probe.
  --user USER               SSH user. Default: current local user.
  --link-local IPV6         Known Pi link-local IPv6 address without %scope.
  --interface IFACE         Workstation network interface for link-local probes.
  --timeout SEC             Connect timeout for ping and SSH probes. Default: 5.
  -h, --help                Show this help and exit.
EOF
}

probe_cmd() {
  local description="$1"
  shift

  info "$description"
  if "$@"; then
    ok "$description succeeded"
  else
    warn "$description failed"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      require_value "$1" "${2:-}"
      HOST="$2"
      shift 2
      ;;
    --user)
      require_value "$1" "${2:-}"
      PI_USER="$2"
      shift 2
      ;;
    --link-local)
      require_value "$1" "${2:-}"
      LINK_LOCAL="$2"
      shift 2
      ;;
    --interface)
      require_value "$1" "${2:-}"
      INTERFACE="$2"
      shift 2
      ;;
    --timeout)
      require_value "$1" "${2:-}"
      [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] \
        || fail "--timeout must be a positive integer (seconds)."
      TIMEOUT_SEC="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

[[ -n "$HOST" ]] || fail "--host is required."
[[ "$TIMEOUT_SEC" =~ ^[1-9][0-9]*$ ]] \
  || fail "--timeout must be a positive integer (seconds)."
require_commands getent ip ping ssh

if [[ -n "$LINK_LOCAL" && -z "$INTERFACE" ]]; then
  fail "--interface is required when --link-local is set."
fi
if [[ -n "$LINK_LOCAL" && "$LINK_LOCAL" == *%* ]]; then
  fail "--link-local must not include %scope; pass scope via --interface."
fi

HOST_BASE="${HOST%.local}"
HOST_LOCAL="${HOST_BASE}.local"
HOST_ALIASES="$HOST_BASE"
if [[ "$HOST_LOCAL" != "$HOST_BASE" ]]; then
  HOST_ALIASES="${HOST_BASE} ${HOST_LOCAL}"
fi

info "Resolver view for ${HOST_BASE}"
getent hosts "$HOST_BASE" || true
getent ahosts "$HOST_BASE" || true

info "Resolver view for ${HOST_LOCAL}"
getent hosts "$HOST_LOCAL" || true
if command -v avahi-resolve >/dev/null 2>&1; then
  avahi-resolve -n "$HOST_LOCAL" || true
fi

if [[ -n "$INTERFACE" ]]; then
  info "Local IPv6 addresses on ${INTERFACE}"
  ip -6 addr show dev "$INTERFACE" || true
fi

probe_cmd "Ping ${HOST_BASE}" ping -c 1 -W "$TIMEOUT_SEC" "$HOST_BASE"
probe_cmd "Ping ${HOST_LOCAL}" ping -c 1 -W "$TIMEOUT_SEC" "$HOST_LOCAL"

if [[ -n "$LINK_LOCAL" ]]; then
  SCOPED_LINK_LOCAL="${LINK_LOCAL}%${INTERFACE}"
  probe_cmd "Ping ${SCOPED_LINK_LOCAL}" ping -6 -c 1 -W "$TIMEOUT_SEC" "$SCOPED_LINK_LOCAL"

  info "SSH probe through scoped link-local"
  if ssh -6 \
    -o BatchMode=yes \
    -o ConnectTimeout="$TIMEOUT_SEC" \
    -o HostKeyAlias="$HOST_BASE" \
    "${PI_USER}@${SCOPED_LINK_LOCAL}" \
    'hostname && whoami'; then
    ok "Scoped link-local SSH succeeded"
    cat <<EOF

Recommended SSH config:
Host ${HOST_ALIASES}
    User ${PI_USER}
    HostName ${LINK_LOCAL}%${INTERFACE}
    AddressFamily inet6
    HostKeyAlias ${HOST_BASE}
    ConnectTimeout ${TIMEOUT_SEC}
EOF
  else
    warn "Scoped link-local SSH failed"
  fi
fi

info "Rendered SSH configuration for ${HOST_BASE}"
ssh -G "$HOST_BASE" | sed -n '1,20p' || true
