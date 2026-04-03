#!/usr/bin/env bash
# Install the latest stable GitHub version of Bluetooth 2 USB. Handles installing submodules, too. 

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
  if [ "${no_newline_flag}" == "-n" ]; then
    echo -ne "${colored_message}"
  else
    echo -e "${colored_message}"
  fi
}

abort_install() {
  local message="$1"
  colored_output "${RED}" "Aborting installation. ${message}"
  exit 1
}

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
    colored_output "${RED}" "This script must be run as root. Attempting to elevate privileges..."
    # Re-run the script as root
    exec sudo bash "$0" "$@"
fi

# Function to append text to a file if the text doesn't already exist in the file
append_if_not_exist() {
  local text="$1"
  local file="$2"
  local backup="${file}.bak"
  # Create a backup of the original file
  cp "${file}" "${backup}" || abort_install "Failed creating backup of ${file}."
  if ! grep -q "^${text}" "${file}"; then
    echo "${text}" >> "${file}" || abort_install "Failed writing to ${file}."
  fi
}

# Function to cleanup before exiting
cleanup() {
  # Re-enable history expansion
  set -H
}

main() {
  # Install prerequisites.
  colored_output "${GREEN}" "Installing bluetooth_2_usb prerequisites..."
  { apt-get update && apt-get install -y git python3.11 python3.11-venv ; } || abort_install "Failed installing prerequisites."

  # Determine the current script's directory and the parent directory
  scripts_directory=$(dirname $(readlink -f "$0"))
  base_directory=$(dirname "${scripts_directory}")
  cd "${base_directory}"

  # Capture the current user and group ownership 
  current_user=$(stat -c '%U' .) || abort_update "Failed retrieving current user ownership."
  current_group=$(stat -c '%G' .) || abort_update "Failed retrieving current group ownership."

  colored_output "${GREEN}" "Creating Python virtual environment \"${base_directory}/.venv\"..."
  python3.11 -m venv .venv || abort_install "Failed creating Python virtual environment."

  colored_output "${GREEN}" "Installing dependencies in venv..."
  .venv/bin/pip3.11 install -r requirements.txt -c constraints.txt || abort_install "Failed installing dependencies."

  # Modify system files.
  colored_output "${GREEN}" "Modifying system files..."
  append_if_not_exist "dtoverlay=dwc2" "/boot/config.txt"
  append_if_not_exist "dwc2" "/etc/modules"
  append_if_not_exist "libcomposite" "/etc/modules"
  cp /boot/cmdline.txt /boot/cmdline.txt.bak || colored_output "${YELLOW}" "Failed creating backup of /boot/cmdline.txt."
  sed -i 's/modules-load=[^[:space:]]* //g' /boot/cmdline.txt || abort_install "Failed writing to /boot/cmdline.txt."
  sed -i 's/rootwait/rootwait modules-load=dwc2/g' /boot/cmdline.txt || abort_install "Failed writing to /boot/cmdline.txt."
  ln -s "${base_directory}/bluetooth_2_usb.sh" /usr/bin/bluetooth_2_usb || colored_output "${YELLOW}" "Failed creating symlink."
  ln -s "${base_directory}/bluetooth_2_usb.service" /etc/systemd/system/ || colored_output "${YELLOW}" "Failed creating symlink."

  # Enable service.
  systemctl enable bluetooth_2_usb.service || abort_install "Failed enabling service."
  systemctl start bluetooth_2_usb.service || abort_install "Failed starting service."

  chown -R ${current_user}:${current_group} "${base_directory}"

  version=$(/usr/bin/bluetooth_2_usb -v)
  if [[ $version == *"Bluetooth 2 USB"* ]]; then
    colored_output "${GREEN}" "Installation successful. Now running ${version}"
    colored_output "${YELLOW}" "A reboot might be required."
  else
    colored_output "${RED}" "Installation failed. The version information could not be retrieved."
  fi
}

# Trap EXIT signal and call cleanup function
trap cleanup EXIT
# Create log dir 
mkdir /var/log/bluetooth_2_usb || colored_output "${YELLOW}" "Failed creating log dir."
# Call the main function and pipe its output to tee
main 2>&1 | tee  /var/log/bluetooth_2_usb/install.log
