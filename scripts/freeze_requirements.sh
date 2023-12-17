#!/usr/bin/env bash
# Freezes the dependencies of Bluetooth 2 USB into requirements.txt

# Determine the current script's directory and the parent directory
scripts_directory=$(dirname $(readlink -f "$0"))
base_directory=$(dirname "${scripts_directory}")
cd "${base_directory}"

venv/bin/pip3.11 freeze > requirements.txt
