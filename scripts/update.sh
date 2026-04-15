#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
# shellcheck source=./lib/paths.sh
source "${SCRIPT_DIR}/lib/paths.sh"
# shellcheck source=./lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
  cat <<EOF
Usage: sudo ./scripts/update.sh

Fast-forward the current managed checkout in ${B2U_INSTALL_DIR} and then
reapply the managed install via ${B2U_INSTALL_DIR}/scripts/install.sh.
EOF
}

case "${1:-}" in
  "") ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    fail "Unknown option: $1"
    ;;
esac

ensure_root
prepare_log "update"
require_commands git

[[ "$B2U_REPO_ROOT" == "$B2U_INSTALL_DIR" ]] || fail "Clone this repository to ${B2U_INSTALL_DIR} and run ./scripts/update.sh from there."
[[ -d "${B2U_INSTALL_DIR}/.git" ]] || fail "Expected a git checkout at ${B2U_INSTALL_DIR}."

if [[ -n "$(git -C "${B2U_INSTALL_DIR}" status --porcelain --untracked-files=all)" ]]; then
  fail "Refusing to update a dirty managed checkout at ${B2U_INSTALL_DIR}. Commit, stash, or remove local changes first."
fi

CURRENT_BRANCH="$(git -C "${B2U_INSTALL_DIR}" symbolic-ref --quiet --short HEAD)" \
  || fail "Refusing to update a detached HEAD in ${B2U_INSTALL_DIR}."

info "Fetching origin for branch ${CURRENT_BRANCH}"
git -C "${B2U_INSTALL_DIR}" fetch --tags --prune origin

info "Fast-forwarding ${CURRENT_BRANCH}"
git -C "${B2U_INSTALL_DIR}" pull --ff-only origin "${CURRENT_BRANCH}"

info "Reapplying managed install"
"${B2U_INSTALL_DIR}/scripts/install.sh"
