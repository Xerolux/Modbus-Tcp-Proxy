#!/bin/bash

set -e

# Variables
REPO_URL="https://github.com/Xerolux/Modbus-Tcp-Proxy.git"
BASE_DIR="/opt/Modbus-Tcp-Proxy"
INSTALL_SCRIPT="$BASE_DIR/install.sh"

# Function to update and re-execute the latest script
update_and_execute_latest() {
    echo "Checking for the latest install script..."
    if [ -d "$BASE_DIR/.git" ]; then
        echo "Updating repository..."
        git -C "$BASE_DIR" fetch
        git -C "$BASE_DIR" reset --hard origin/main
    else
        echo "Cloning repository..."
        git clone "$REPO_URL" "$BASE_DIR"
    fi

    # Check if the install script has changed
    if [ "$(sha256sum "$INSTALL_SCRIPT" | awk '{print $1}')" != "$(git -C "$BASE_DIR" show origin/main:install.sh | sha256sum | awk '{print $1}')" ]; then
        echo "Install script updated. Re-executing the latest version..."
        exec bash "$INSTALL_SCRIPT" "$@"
    fi
}

# Check and update the script
if [ "$(basename "$0")" != "install.sh" ]; then
    # If not running from the expected path, copy the script and restart
    cp "$0" "$INSTALL_SCRIPT"
    exec bash "$INSTALL_SCRIPT" "$@"
else
    update_and_execute_latest
fi

# Installation process
echo "Starting the installation process..."

# Update and install dependencies
echo "Updating system and installing dependencies..."
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git bc || { echo "Failed to install dependencies. Exiting."; exit 1; }

# Create base directory
if [ ! -d "$BASE_DIR" ]; then
    echo "Creating base directory at $BASE_DIR..."
    sudo mkdir -p "$BASE_DIR"
    sudo chown $USER:$USER "$BASE_DIR"
else
    echo "Base directory already exists at $BASE_DIR."
fi

# Clone or update repository
if [ -d "$BASE_DIR/.git" ]; then
    echo "Updating repository..."
    git -C "$BASE_DIR" fetch && git -C "$BASE_DIR" reset --hard origin/main || { echo "Git update failed. Exiting."; exit 1; }
else
    echo "Cloning repository from $REPO_URL..."
    git clone "$REPO_URL" "$BASE_DIR" || { echo "Git clone failed. Exiting."; exit 1; }
fi

# Verify Python version
python3 -c "import sys; assert sys.version_info >= (3, 7), 'Python 3.7 or newer is required.'" || { echo "Unsupported Python version. Exiting."; exit 1; }

# Create or activate virtual environment
VENV_DIR="$BASE_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR" || { echo "Failed to create virtual environment. Exiting."; exit 1; }
else
    echo "Virtual environment already exists."
fi
source "$VENV_DIR/bin/activate"

# Install Python dependencies
REQ_FILE="$BASE_DIR/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    echo "requirements.txt not found. Exiting."
    deactivate
    exit 1
fi
echo "Installing Python dependencies..."
pip install -r "$REQ_FILE" || { echo "Failed to install Python dependencies. Exiting."; deactivate; exit 1; }

# Ensure the Modbus proxy is ready to run
echo "Installation complete! Use 'sudo systemctl restart modbus_proxy.service' to apply changes."
