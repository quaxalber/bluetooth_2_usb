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

# Check if the script is running as root and elevate privileges if not
if [[ $EUID -ne 0 ]]; then
  colored_output ${RED} "This script must be run as root. Attempting to elevate privileges..."
  # Re-run the script as root
  exec sudo bash "$0" "$@"
fi

PY_VER_MINOR="3.11"
PY_VER_PATCH="3.11.5"

colored_output ${GREEN} "Installing Python $PY_VER_MINOR from source as Debian package..."

# Update package list and install prerequisites
colored_output ${GREEN} "Updating package list and installing prerequisites..."
apt-get update -y || exit 1
apt-get install -y build-essential zlib1g-dev libc6-dev libncursesw5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev wget checkinstall || exit 1

# Download and extract Python source code
colored_output ${GREEN} "Downloading Python $PY_VER_MINOR source code..."
PY_SRC_DIR="Python-$PY_VER_PATCH"
PY_TARBALL="$PY_SRC_DIR.tgz"
wget "https://www.python.org/ftp/python/$PY_VER_PATCH/$PY_TARBALL" || exit 1
tar -zxvf "$PY_TARBALL" || exit 1
rm "$PY_TARBALL"

colored_output ${GREEN} "Configuring and compiling Python $PY_VER_MINOR..."
cd "$PY_SRC_DIR"
# Configure Python with optimizations
./configure --enable-optimizations
# Compile Python utilizing all available cores
make -j$(nproc) || exit 1

# Install Python as Debian package using checkinstall
colored_output ${GREEN} "Installing Python $PY_VER_MINOR as a Debian package..."
sudo checkinstall -y || exit 1

# Cleanup
colored_output ${GREEN} "Performing cleanup..."
cd ..
if [[ -z "$PY_SRC_DIR" ]]; then
  colored_output ${RED} "PY_SRC_DIR is empty. Exiting to avoid potential data loss."
  exit 1
fi

colored_output ${GREEN} "Going to remove no longer needed files and directories under: $PY_SRC_DIR "

# Check for automation flag to bypass prompt
if [ "$AUTO" == "true" ]; then
  REPLY="y"
else
  colored_output ${YELLOW} "Continue removal? (y/n): " -n
  # Read single character input
  read -n 1 -r
fi

echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
  rm -rf "$PY_SRC_DIR"
fi

# Verify installation
if ! command -v python"$PY_VER_MINOR" &> /dev/null; then
  colored_output ${RED} "Installation failed!"
else
  colored_output ${GREEN} "Successfully installed $(python"$PY_VER_MINOR" --version) as Debian package python$PY_VER_MINOR.
  You may now use your usual package management tools such as apt or dpkg to remove this package if no longer needed. "
fi

# Re-enable history expansion
set -H
