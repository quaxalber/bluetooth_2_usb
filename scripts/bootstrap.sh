#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO_URL="${B2U_BOOTSTRAP_REPO:-https://github.com/quaxalber/bluetooth_2_usb.git}"
REPO_BRANCH="${B2U_BOOTSTRAP_BRANCH:-main}"
INSTALL_DIR="/opt/bluetooth_2_usb"
NO_REBOOT=0

usage() {
  cat <<EOF
Usage: curl .../bootstrap.sh | sudo bash [-- options]
  --repo <url>       Repository URL. Default: ${REPO_URL}
  --branch <name>    Branch or tag to install. Default: ${REPO_BRANCH}
  --dir <path>       Install directory. Default: ${INSTALL_DIR}
  --no-reboot        Do not prompt for reboot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO_URL="$2"; shift 2 ;;
    --branch) REPO_BRANCH="$2"; shift 2 ;;
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --no-reboot) NO_REBOOT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  printf 'Run this bootstrap script as root, for example via: curl ... | sudo bash\n' >&2
  exit 1
fi

for cmd in bash curl tar mktemp python3; do
  command -v "$cmd" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$cmd" >&2
    exit 1
  }
done

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

install_args=(--repo "$REPO_URL" --branch "$REPO_BRANCH" --dir "$INSTALL_DIR")
if [[ $NO_REBOOT -eq 1 ]]; then
  install_args+=(--no-reboot)
fi

exec bash "${repo_dir}/scripts/install.sh" "${install_args[@]}"
