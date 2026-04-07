#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO_URL="${B2U_BOOTSTRAP_REPO:-https://github.com/quaxalber/bluetooth_2_usb.git}"
REPO_BRANCH="${B2U_BOOTSTRAP_BRANCH:-}"
NO_REBOOT=0

usage() {
  local default_branch_label
  if [[ -n "$REPO_BRANCH" ]]; then
    default_branch_label="$REPO_BRANCH"
  else
    default_branch_label="latest published release"
  fi
  cat <<EOF
Usage: curl .../bootstrap.sh | sudo bash -s -- [options]
  --repo <url>       Repository URL. Default: ${REPO_URL}
  --branch <name>    Branch or tag to install. Default: ${default_branch_label}
  --no-reboot        Do not prompt for reboot
EOF
}

require_value() {
  local opt="$1"
  [[ $# -ge 2 && -n "${2:-}" && "${2:-}" != -* ]] || {
    printf 'Missing value for %s\n' "$opt" >&2
    exit 1
  }
}

github_repo_slug() {
  local repo_url="$1"
  case "$repo_url" in
    https://github.com/*) repo_url="${repo_url#https://github.com/}" ;;
    http://github.com/*) repo_url="${repo_url#http://github.com/}" ;;
    git@github.com:*) repo_url="${repo_url#git@github.com:}" ;;
    ssh://git@github.com/*) repo_url="${repo_url#ssh://git@github.com/}" ;;
    *) return 1 ;;
  esac
  repo_url="${repo_url%.git}"
  [[ "$repo_url" == */* ]] || return 1
  printf '%s\n' "$repo_url"
}

resolve_latest_release_tag() {
  local repo_url="$1"
  local repo_slug
  local api_url
  local response
  local tag_name

  repo_slug="$(github_repo_slug "$repo_url")" || return 1
  api_url="https://api.github.com/repos/${repo_slug}/releases/latest"
  response="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api_url")" || return 1
  tag_name="$(printf '%s' "$response" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  [[ -n "$tag_name" ]] || return 1
  printf '%s\n' "$tag_name"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      require_value "$1" "${2:-}"
      REPO_URL="$2"
      shift 2
      ;;
    --branch)
      require_value "$1" "${2:-}"
      REPO_BRANCH="$2"
      shift 2
      ;;
    --no-reboot)
      NO_REBOOT=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  printf 'Run this bootstrap script as root, for example via: curl ... | sudo bash\n' >&2
  exit 1
fi

for cmd in bash curl sed tar mktemp; do
  command -v "$cmd" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$cmd" >&2
    exit 1
  }
done

if [[ -z "$REPO_BRANCH" ]]; then
  if REPO_BRANCH="$(resolve_latest_release_tag "$REPO_URL")"; then
    printf 'No --branch supplied; using latest published release: %s\n' "$REPO_BRANCH"
  else
    REPO_BRANCH="main"
    printf 'Could not resolve the latest published release for %s. Falling back to: %s\n' "$REPO_URL" "$REPO_BRANCH" >&2
  fi
fi

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

archive_path="${tmpdir}/bluetooth_2_usb.tar.gz"

archive_urls=(
  "${REPO_URL%.git}/archive/refs/heads/${REPO_BRANCH}.tar.gz"
  "${REPO_URL%.git}/archive/refs/tags/${REPO_BRANCH}.tar.gz"
)

downloaded=0
for archive_url in "${archive_urls[@]}"; do
  printf 'Downloading %s\n' "$archive_url"
  if curl -fsSL "$archive_url" -o "$archive_path"; then
    downloaded=1
    break
  fi
done

[[ $downloaded -eq 1 ]] || {
  printf 'Failed to download repository archive for %s from %s\n' "$REPO_BRANCH" "$REPO_URL" >&2
  exit 1
}

tar -xzf "$archive_path" -C "$tmpdir"

repo_dir="$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[[ -n "$repo_dir" ]] || {
  printf 'Failed to extract repository archive.\n' >&2
  exit 1
}

install_args=(--repo "$REPO_URL" --branch "$REPO_BRANCH")
if [[ $NO_REBOOT -eq 1 ]]; then
  install_args+=(--no-reboot)
fi

bash "${repo_dir}/scripts/install.sh" "${install_args[@]}"
