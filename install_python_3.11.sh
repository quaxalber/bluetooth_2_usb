#!/usr/bin/env bash

# Check for superuser privileges
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root. Attempting to elevate privileges..."
    # Re-run the script as root
    exec sudo bash "$0" "$@"
fi

PY_VER="3.11.5"
wget "https://www.python.org/ftp/python/$PY_VER/Python-$PY_VER.tgz"
tar -zxvf "Python-$PY_VER.tgz"
cd "Python-$PY_VER"
./configure --enable-optimizations
make altinstall