#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
exec "${SCRIPT_DIR}/host_relay_test_capture.sh" "$@"
