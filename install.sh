#!/usr/bin/env bash
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

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
    colored_output ${RED} "This script must be run as root. Attempting to elevate privileges..."
    # Re-run the script as root
    exec sudo bash "$0" "$@"
fi

# Function to append text to a file if the text doesn't already exist in the file
append_if_not_exist() {
  TEXT="$1"
  FILE="$2"
  BACKUP="$FILE.bak"

  # Create a backup of the original file
  cp "$FILE" "$BACKUP"

  if ! grep -q "^$TEXT" "$FILE"; then
    echo "$TEXT" | tee -a "$FILE" > /dev/null
  fi
}

colored_output ${GREEN} "Installing bluetooth_2_usb..."

append_if_not_exist "dtoverlay=dwc2" "/boot/config.txt"
append_if_not_exist "dwc2" "/etc/modules"
append_if_not_exist "libcomposite" "/etc/modules"

# Check if python3.11 & pip3.11 are installed and install if not
if ! (command -v python3.11 && command -v pip3.11) &> /dev/null; then
  bash install_python_3.11.sh
else
  colored_output ${GREEN} "$(python3.11 --version) already installed"
fi

colored_output ${GREEN} "Installing required Python packages..."
pip3.11 install evdev

currentScriptDirectory=$(dirname $(readlink -f $0))

mkdir /var/log/bluetooth_2_usb

chmod 744 $currentScriptDirectory/bluetooth_2_usb.py
ln -s $currentScriptDirectory/bluetooth_2_usb.py /usr/bin/
ln -s $currentScriptDirectory/bluetooth_2_usb.service /etc/systemd/system/

systemctl enable bluetooth_2_usb.service

# Check for automation flag to bypass prompt
if [ "$AUTO" == "true" ]; then
  REPLY="y"
else
  # Notify user about the reboot
  colored_output ${YELLOW} "The system needs to reboot to complete the installation. Reboot now? (y/n) " -n
  # Read single character input
  read -n 1 -r
fi

echo

# Re-enable history expansion
set -H

if [[ $REPLY =~ ^[Yy]$ ]]; then
    reboot
fi
