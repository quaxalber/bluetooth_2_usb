#!/usr/bin/env bash
set -e  # Exit immediately on error

script_directory=$(dirname "$(readlink -f "$0")")

if [ ! -d "${script_directory}/venv" ]; then
  echo "Error: virtual environment not found."
  exit 1
fi

source "${script_directory}/venv/bin/activate" || {
  echo "Error: failed to activate virtual environment."
  exit 1
}

python3 "${script_directory}/bluetooth_2_usb.py" "$@" || {
  echo "Error: Python script failed."
  deactivate
  exit 1
}

deactivate