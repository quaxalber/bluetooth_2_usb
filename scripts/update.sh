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
  exit 1
}

# Function to cleanup before exiting
cleanup() {
  # Re-enable history expansion
  set -H
}

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
  colored_output "${RED}" "This script must be run as root. Attempting to elevate privileges..."
  # Re-run the script as root
  exec sudo bash "$0" "$@"
fi

# Trap EXIT signal and call cleanup function
trap cleanup EXIT

# Determine the current script's directory and the parent directory
scripts_directory=$(dirname $(readlink -f "$0"))
base_directory=$(dirname "${scripts_directory}")
cd "${base_directory}"

current_version=$(/usr/bin/bluetooth_2_usb -v)
latest_vesion=$(git tag -l | sort -V | tail -n1)
colored_output "${GREEN}" "Updating ${current_version} -> ${latest_vesion}..."

# Capture the current user and group ownership and branch
current_user=$(stat -c '%U' .) || abort_update "Failed retrieving current user ownership."
current_group=$(stat -c '%G' .) || abort_update "Failed retrieving current group ownership."
current_branch=$(git symbolic-ref --short HEAD) || abort_update "Failed retrieving currently checked out branch."

{
  scripts/uninstall.sh && 
  cd .. &&  
  rm -rf "${base_directory}" && 
  git clone https://github.com/quaxalber/bluetooth_2_usb.git &&  
  cd "${base_directory}" && 
  git checkout "${current_branch}" &&
  chown -R ${current_user}:${current_group} "${base_directory}" &&
  scripts/install.sh ; 
} || abort_update "Failed updating Bluetooth 2 USB"
