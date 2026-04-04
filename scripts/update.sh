#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

INSTALL_DIR="$B2U_DEFAULT_INSTALL_DIR"
SERVICE_NAME="$B2U_DEFAULT_SERVICE_NAME"
REPO_URL="$(default_repo_url)"
REPO_BRANCH="$(default_repo_branch)"
RESTART=1

usage() {
  cat <<EOF
Usage: sudo ./update.sh [options]
  --dir <path>        Install directory. Default: ${B2U_DEFAULT_INSTALL_DIR}
  --repo <url|path>   Override repository source
  --branch <name>     Override branch/tag
  --service <name>    Service name. Default: ${B2U_DEFAULT_SERVICE_NAME}
  --no-restart        Do not restart the service after update
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --branch) REPO_BRANCH="$2"; shift 2 ;;
    --service) SERVICE_NAME="$2"; shift 2 ;;
    --no-restart) RESTART=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "update"
require_commands git python3 systemctl

[[ -d "$INSTALL_DIR" ]] || fail "Install directory not found: $INSTALL_DIR"
VENV_DIR="${INSTALL_DIR}/venv"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
  if [[ -n "$REPO_URL" ]]; then
    git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
  fi
  info "Updating repository in ${INSTALL_DIR}"
  git -C "$INSTALL_DIR" fetch --all --tags
  if [[ -n "$REPO_BRANCH" ]]; then
    git -C "$INSTALL_DIR" checkout "$REPO_BRANCH"
  fi
  if git -C "$INSTALL_DIR" symbolic-ref -q HEAD >/dev/null; then
    git -C "$INSTALL_DIR" pull --ff-only origin "$REPO_BRANCH"
  fi
elif [[ -n "$REPO_URL" && -n "$REPO_BRANCH" ]]; then
  info "Replacing non-git installation using ${REPO_URL}@${REPO_BRANCH}"
  tmpdir="$(mktemp -d)"
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "${tmpdir}/repo"
  rm -rf "$INSTALL_DIR"
  mv "${tmpdir}/repo" "$INSTALL_DIR"
else
  fail "Install directory is not a git checkout. Provide --repo and --branch to replace it."
fi

info "Recreating virtual environment at ${VENV_DIR}"
recreate_venv "$VENV_DIR"

"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install --upgrade "$INSTALL_DIR"
install_service_unit "$INSTALL_DIR" "$SERVICE_NAME"
write_default_env_file
install_cli_wrapper "$INSTALL_DIR"
systemctl daemon-reload

if [[ $RESTART -eq 1 ]]; then
  systemctl restart "${SERVICE_NAME}.service"
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
fi

ok "Update complete"
