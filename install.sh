#!/usr/bin/env bash

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root. Attempting to elevate privileges..."
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

# Check if pip3 is installed, if not, install it
if ! command -v pip3 &> /dev/null; then
    apt-get update
    apt-get install -y python3-pip
fi

append_if_not_exist "dtoverlay=dwc2" "/boot/config.txt"
append_if_not_exist "dwc2" "/etc/modules"
append_if_not_exist "libcomposite" "/etc/modules"

pip3 install evdev adafruit-circuitpython-hid

currentScriptDirectory=$(dirname $(readlink -f $0))

mkdir /var/log/bluetooth_2_usb

chmod 744 $currentScriptDirectory/bluetooth_2_usb.py
ln -s $currentScriptDirectory/bluetooth_2_usb.py /usr/bin/
ln -s $currentScriptDirectory/bluetooth_2_usb.service /etc/systemd/system/

systemctl enable bluetooth_2_usb.service

# Notify user about the reboot
read -p "The system needs to reboot to complete the installation. Reboot now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    reboot
fi
