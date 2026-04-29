#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/venv/bin/python"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PYTHON_BIN" -m bluetooth_2_usb.ops smoketest --repo-root "$REPO_ROOT" "$@"
