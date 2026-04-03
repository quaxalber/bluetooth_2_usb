#!/usr/bin/env bash
# Main entry script for bluetooth_2_usb

script_directory=$(dirname $(readlink -f "$0"))
source "${script_directory}/.venv/bin/activate"
python3.11 "${script_directory}/bluetooth_2_usb.py" "$@"
deactivate
