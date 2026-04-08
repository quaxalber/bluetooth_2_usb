#!/usr/bin/env bash

if [[ -n "${B2U_COMMON_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_COMMON_SH_SOURCED=1

_b2u_common_dir="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./paths.sh
source "${_b2u_common_dir}/paths.sh"
unset _b2u_common_dir

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[1;36m'
BOLD=$'\033[1m'
NC=$'\033[0m'

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

backup_file() {
  local file="$1"

  [[ -f "$file" ]] || return 0
  cp -a "$file" "${file}.bak.$(timestamp)"
}
