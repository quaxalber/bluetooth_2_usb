#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=./lib/common.sh
source "$(cd -- "$(dirname "$0")" && pwd)/lib/common.sh"

REPO_URL="$(default_repo_url)"
REPO_REF="$(default_repo_ref)"
REF_MODE=""
RESTART=1

usage() {
  cat <<EOF
Usage: sudo ./update.sh [options]
  --repo <url|path>   Override repository source
  --branch <name>     Override branch/tag
  --latest-release    Update to the latest published release tag from GitHub
  --no-restart        Update without starting the service; requires it to already be stopped
EOF
}

EXPLICIT_REPO=0
EXPLICIT_REF=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      require_value "$1" "${2:-}"
      REPO_URL="$2"
      EXPLICIT_REPO=1
      shift 2
      ;;
    --branch)
      require_value "$1" "${2:-}"
      [[ $EXPLICIT_REF -eq 0 ]] || fail "Use either --branch or --latest-release, not both."
      REPO_REF="$2"
      REF_MODE="pinned"
      EXPLICIT_REF=1
      shift 2
      ;;
    --latest-release)
      [[ $EXPLICIT_REF -eq 0 ]] || fail "Use either --branch or --latest-release, not both."
      REPO_REF=""
      REF_MODE="release"
      EXPLICIT_REF=1
      shift
      ;;
    --no-restart)
      RESTART=0
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) fail "Unknown option: $1" ;;
  esac
done

ensure_root
prepare_log "update"
require_commands git install python3 systemctl

[[ -d "$B2U_INSTALL_DIR" ]] || fail "Install directory not found: $B2U_INSTALL_DIR"
VENV_DIR="${B2U_INSTALL_DIR}/venv"
SERVICE_WAS_ACTIVE=0
load_managed_source_config

if [[ $EXPLICIT_REPO -eq 0 && -n "${B2U_MANAGED_REPO_URL:-}" ]]; then
  REPO_URL="$B2U_MANAGED_REPO_URL"
fi
if [[ $EXPLICIT_REF -eq 0 ]]; then
  case "${B2U_MANAGED_REF_MODE:-}" in
    branch | tag)
      REF_MODE="pinned"
      REPO_REF="$B2U_MANAGED_REF"
      ;;
    release)
      REF_MODE="release"
      REPO_REF=""
      ;;
  esac
fi

REF_MODE="${REF_MODE:-pinned}"

if [[ "$REF_MODE" == "release" ]]; then
  resolved_release_tag="$(resolve_latest_release_tag "$REPO_URL")" || fail "Could not resolve the latest published release for ${REPO_URL}. Pass --branch explicitly if you want a non-release ref."
  REPO_REF="$resolved_release_tag"
  info "Updating to latest published release: ${REPO_REF}"
fi

if systemctl is-active --quiet "${B2U_SERVICE_UNIT}" 2>/dev/null; then
  SERVICE_WAS_ACTIVE=1
fi
if [[ $RESTART -eq 0 && $SERVICE_WAS_ACTIVE -eq 1 ]]; then
  fail "--no-restart is only supported when ${B2U_SERVICE_UNIT} is already stopped."
fi
if [[ $SERVICE_WAS_ACTIVE -eq 1 ]]; then
  info "Stopping ${B2U_SERVICE_UNIT} before updating the managed installation"
  systemctl stop "${B2U_SERVICE_UNIT}" || fail "Failed to stop ${B2U_SERVICE_UNIT}"
fi

if [[ -d "${B2U_INSTALL_DIR}/.git" ]]; then
  ensure_repo_remote "$B2U_INSTALL_DIR" "$REPO_URL"
  info "Updating repository in ${B2U_INSTALL_DIR}"
  git -C "$B2U_INSTALL_DIR" fetch --all --tags
  git -C "$B2U_INSTALL_DIR" checkout "$REPO_REF"
  if git -C "$B2U_INSTALL_DIR" symbolic-ref -q HEAD >/dev/null; then
    current_branch="$(checkout_ref_name "$B2U_INSTALL_DIR")"
    git -C "$B2U_INSTALL_DIR" pull --ff-only origin "$current_branch"
  fi
else
  info "Replacing non-git installation using ${REPO_URL}@${REPO_REF}"
  tmpdir="$(mktemp -d)"
  git clone --branch "$REPO_REF" "$REPO_URL" "${tmpdir}/repo"
  rm -rf "$B2U_INSTALL_DIR"
  mv "${tmpdir}/repo" "$B2U_INSTALL_DIR"
  rmdir "$tmpdir" 2>/dev/null || true
fi

checkout_mode="$(checkout_ref_mode "$B2U_INSTALL_DIR")"
case "$checkout_mode" in
  branch)
    stored_ref="$(checkout_ref_name "$B2U_INSTALL_DIR")"
    stored_mode="branch"
    ;;
  tag)
    stored_ref="$(checkout_ref_name "$B2U_INSTALL_DIR")"
    stored_mode="${REF_MODE:-tag}"
    [[ "$stored_mode" == "release" ]] || stored_mode="tag"
    ;;
  *)
    fail "Managed checkout is neither on a branch nor an exact tag after update."
    ;;
esac
write_managed_source_config "$REPO_URL" "$stored_mode" "$stored_ref"

info "Recreating virtual environment at ${VENV_DIR}"
recreate_venv "$VENV_DIR"

"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install --upgrade "$B2U_INSTALL_DIR"
install_service_unit
write_default_env_file
install_cli_wrapper
systemctl daemon-reload

if [[ $RESTART -eq 1 ]]; then
  if [[ $SERVICE_WAS_ACTIVE -eq 1 ]]; then
    info "Restarting ${B2U_SERVICE_UNIT}"
  else
    info "Starting ${B2U_SERVICE_UNIT}"
  fi
  systemctl restart "${B2U_SERVICE_UNIT}"
  systemctl --no-pager --full status "${B2U_SERVICE_UNIT}" || true
else
  info "Leaving ${B2U_SERVICE_UNIT} stopped after update (--no-restart)"
fi

ok "Update complete"
