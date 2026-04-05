#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

REPO_URL="$(default_repo_url)"
REPO_BRANCH="$(default_repo_branch)"
RESTART=1

usage() {
  cat <<EOF
Usage: sudo ./update.sh [options]
  --repo <url|path>   Override repository source
  --branch <name>     Override branch/tag
  --no-restart        Do not restart the service after update
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) require_value "$1" "${2:-}"; REPO_URL="$2"; shift 2 ;;
    --branch) require_value "$1" "${2:-}"; REPO_BRANCH="$2"; shift 2 ;;
    --no-restart) RESTART=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "update"
require_commands git install python3 systemctl

[[ -d "$B2U_INSTALL_DIR" ]] || fail "Install directory not found: $B2U_INSTALL_DIR"
VENV_DIR="${B2U_INSTALL_DIR}/venv"

if [[ -d "${B2U_INSTALL_DIR}/.git" ]]; then
  if [[ -n "$REPO_URL" ]]; then
    if git -C "$B2U_INSTALL_DIR" remote get-url origin >/dev/null 2>&1; then
      git -C "$B2U_INSTALL_DIR" remote set-url origin "$REPO_URL"
    else
      git -C "$B2U_INSTALL_DIR" remote add origin "$REPO_URL"
    fi
  fi
  info "Updating repository in ${B2U_INSTALL_DIR}"
  git -C "$B2U_INSTALL_DIR" fetch --all --tags
  if [[ -n "$REPO_BRANCH" ]]; then
    git -C "$B2U_INSTALL_DIR" checkout "$REPO_BRANCH"
  fi
  if git -C "$B2U_INSTALL_DIR" symbolic-ref -q HEAD >/dev/null; then
    git -C "$B2U_INSTALL_DIR" pull --ff-only origin "$REPO_BRANCH"
  fi
elif [[ -n "$REPO_URL" && -n "$REPO_BRANCH" ]]; then
  info "Replacing non-git installation using ${REPO_URL}@${REPO_BRANCH}"
  tmpdir="$(mktemp -d)"
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "${tmpdir}/repo"
  rm -rf "$B2U_INSTALL_DIR"
  mv "${tmpdir}/repo" "$B2U_INSTALL_DIR"
  rmdir "$tmpdir" 2>/dev/null || true
else
  fail "Install directory is not a git checkout. Provide --repo and --branch to replace it."
fi

info "Recreating virtual environment at ${VENV_DIR}"
recreate_venv "$VENV_DIR"

"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install --upgrade "$B2U_INSTALL_DIR"
install_service_unit
write_default_env_file
install_cli_wrapper
systemctl daemon-reload

if [[ $RESTART -eq 1 ]]; then
  systemctl restart "${B2U_SERVICE_UNIT}"
  systemctl --no-pager --full status "${B2U_SERVICE_UNIT}" || true
fi

ok "Update complete"
