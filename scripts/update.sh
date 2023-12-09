#!/usr/bin/env bash
# Update Bluetooth 2 USB to the latest stable GitHub version. Handles updating submodules, if required. 

# Temporarily disable history expansion
set +H

# ANSI escape codes for colored output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
# Reset to default color
NC='\033[0m'

colored_output() {
  local color_code="$1"
  local message="$2"
  local colored_message="${color_code}${message}${NC}"
  echo -e "${colored_message}"
}

abort_update() {
  local message="$1"
  colored_output "${RED}" "Aborting update. ${message}"
  # Re-enable history expansion
  set -H
  exit 1
}

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
  colored_output "${RED}" "This script must be run as root. Attempting to elevate privileges..."
  # Re-run the script as root
  exec sudo bash "$0" "$@"
fi

# Determine the current script's directory and the parent directory
scripts_directory=$(dirname $(readlink -f "$0"))
base_directory=$(dirname "${scripts_directory}")
cd "${base_directory}"

colored_output "${GREEN}" "Fetching updates from GitHub..."
remote_name="origin"
current_branch=$(git symbolic-ref --short HEAD || abort_update "Failed retrieving currently checked out branch.")
# Fetch the latest changes from the remote
git fetch ${remote_name} || colored_output "${RED}" "Failed fetching changes from ${remote_name}." ; 

# Compare the local branch with the remote branch
if [ $(git rev-parse HEAD) != $(git rev-parse ${remote_name}/${current_branch}) ]; then
  colored_output "${GREEN}" "Changes are available to pull."
else
  colored_output "${GREEN}" "No changes to pull."
  exit 0
fi

git stash || abort_update "Failed stashing local changes."
git merge || abort_update "Failed merging changes from ${remote_name}."
git stash pop --index || abort_update "Failed applying local changes from stash."

# Loop through each package in requirements.txt
while read package; do
    # Check if the package is outdated
    outdated=$(venv/bin/pip list --outdated | grep -q "${package}")
    
    if [ ! -z "${outdated}" ]; then
        # If the package is outdated, update it
        echo "Updating ${package}"
        venv/bin/pip install --upgrade "${package}"
    else
        echo "${package} is up to date"
    fi
done < requirements.txt

colored_output "${GREEN}" "Restarting service..."
{ systemctl daemon-reload && systemctl restart bluetooth_2_usb.service ; } || abort_update "Failed restarting service."

colored_output "${GREEN}" "Update successful. Now running $(venv/bin/python3.11 bluetooth_2_usb.py -v)"

# Re-enable history expansion
set -H
