#!/usr/bin/env bash
# Uninstall script for bluetooth_2_usb

# ANSI escape codes for colored output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Function for colored output
colored_output() {
  local color_code="$1"
  local message="$2"
  echo -e "${color_code}${message}${NC}"
}

# Determine the current script's directory and the parent directory
scripts_directory=$(dirname $(readlink -f "$0"))
base_directory=$(dirname "${scripts_directory}")
cd "${base_directory}"

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
    colored_output "${RED}" "This script must be run as root. Attempting to elevate privileges..."
    # Re-run the script as root
    exec sudo bash "$0" "$@"
fi

colored_output "${YELLOW}" "Stopping and disabling bluetooth_2_usb service..."
systemctl stop bluetooth_2_usb.service
systemctl disable bluetooth_2_usb.service

colored_output "${YELLOW}" "Removing files and restoring backup files..."
rm /usr/bin/bluetooth_2_usb
rm -rf /var/log/bluetooth_2_usb
mv /boot/config.txt.bak /boot/config.txt
mv /etc/modules.bak /etc/modules
mv /boot/cmdline.txt.bak /boot/cmdline.txt

# Optionally, remove installed packages (if they were not previously installed)
# colored_output "${YELLOW}" "Removing installed packages..."
# apt remove -y git python3.11 python3.11-venv

colored_output "${GREEN}" "Uninstallation complete."
