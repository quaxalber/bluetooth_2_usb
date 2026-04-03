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
  local no_newline_flag="$3"
  local colored_message="${color_code}${message}${NC}"
  if [ "$no_newline_flag" == "-n" ]; then
    echo -ne "$colored_message"
  else
    echo -e "$colored_message"
  fi
}

abort_update() {
  local message="$1"
  colored_output ${RED} "Aborting update. ${message}"
  # Re-enable history expansion
  set -H
  exit 1
}

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
  colored_output ${RED} "This script must be run as root. Attempting to elevate privileges..."
  # Re-run the script as root
  exec sudo bash "$0" "$@"
fi

# Determine the current script's directory and the parent directory
scriptsDirectory=$(dirname $(readlink -f "$0"))
baseDirectory=$(dirname "$scriptsDirectory")
cd "$baseDirectory"

colored_output ${GREEN} "Fetching updates from GitHub..."

remote_name="origin"
current_branch=$(git symbolic-ref --short HEAD  || abort_update "Failed retrieving currently checked out branch.")

# Force Git to use English for its messages, regardless of the user's language settings.
user_lang=$LANG
export LANG=C

# Fetch the latest changes from the remote
fetch_output=$( { git fetch $remote_name || colored_output ${RED} "Failed fetching changes from $remote_name." ; } | tee /dev/tty )

export LANG=$user_lang

# Compare the local branch with the remote branch
if [ $(git rev-parse HEAD) != $(git rev-parse $remote_name/$current_branch) ]; then
  colored_output ${GREEN} "Changes are available to pull."
else
  colored_output ${GREEN} "No changes to pull."
  exit 0
fi

git stash || abort_update "Failed stashing local changes."
git merge || abort_update "Failed merging changes from $remote_name."
git stash pop --index || abort_update "Failed applying local changes from stash."

# Check if there are changes in any submodule 
if echo "$fetch_output" | grep -q "Fetching submodule"; then

  colored_output ${GREEN} "Updating submodules..."

  git submodule update --init --recursive || abort_update "Failed updating submodules."
  venv/bin/pip3.11 install submodules/* || abort_update "Failed installing submodules."

fi

colored_output ${GREEN} "Restarting service..."

{ systemctl daemon-reload && systemctl restart bluetooth_2_usb.service ; } || abort_update "Failed restarting service."

colored_output ${GREEN} "Update successful. Now running $(venv/bin/python3.11 bluetooth_2_usb.py -v)"

# Re-enable history expansion
set -H
