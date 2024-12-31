#!/bin/bash

set -e  # Exit the script if any command fails

# Variables
REPO_URL="https://github.com/Xerolux/Modbus-Tcp-Proxy.git"
BASE_DIR="/opt/Modbus-Tcp-Proxy"
INSTALL_SCRIPT="$BASE_DIR/install.sh"
SERVICE_NAME="modbus_proxy.service"
DEFAULT_CONFIG_FILE="$BASE_DIR/config.default.yaml"
CONFIG_FILE="$BASE_DIR/config.yaml"
MERGE_SCRIPT="$BASE_DIR/merge_config.py"
VERSION_FILE="$BASE_DIR/VERSION"

# Function: Determine the local IP address
get_local_ip() {
    local_ip=$(hostname -I | awk '{print $1}')
    if [[ -z "$local_ip" ]]; then
        echo "Could not determine a local IP address. Ensure the network is working."
        exit 1
    fi
    echo "$local_ip"
}

# Check for Debian 12 or Ubuntu 24
check_os() {
    echo "Checking operating system version..."
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "debian" && "$VERSION_ID" == "12" ]] || [[ "$ID" == "ubuntu" && "$VERSION_ID" == "24.04" ]]; then
            echo "Operating system supported: $PRETTY_NAME"
        else
            echo "Unsupported operating system: $PRETTY_NAME"
            echo "This script supports only Debian 12 and Ubuntu 24."
            exit 1
        fi
    else
        echo "Could not find /etc/os-release. OS check failed."
        exit 1
    fi
}

# Stop the service
stop_service() {
    echo "Stopping $SERVICE_NAME..."
    sudo systemctl stop "$SERVICE_NAME" || echo "$SERVICE_NAME is not running."
}

# Restart or start the service
restart_service() {
    echo "Restarting $SERVICE_NAME..."
    sudo systemctl daemon-reload
    sudo systemctl restart "$SERVICE_NAME"
}

# Display current version and host information
display_info() {
    local version
    local proxy_port
    local_ip=$(get_local_ip)

    version=$(cat "$VERSION_FILE")
    proxy_port=$(grep -Po '(?<=ServerPort: ).*' "$CONFIG_FILE" | head -1)

    echo "Update / Start / Install successful!"
    echo "Version: $version"
    echo "Proxy accessible at: ${local_ip}:${proxy_port}"
}

# Configuration menu: load or edit configuration
config_menu() {
    echo "Checking configuration file..."

    # Create a default configuration if none exists
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "No configuration found. Creating a new configuration file based on default values..."
        cp "$DEFAULT_CONFIG_FILE" "$CONFIG_FILE"
    fi

    # Read the current configuration
    local current_config
    current_config=$(cat "$CONFIG_FILE")

    echo "Current configuration:"
    echo "--------------------------------"
    echo "$current_config"
    echo "--------------------------------"

    # Prompt the user to confirm or edit the configuration
    echo "Do you want to use the current configuration? (y/n)"
    read -r response
    if [[ "$response" =~ ^[nN]$ ]]; then
        echo "Opening configuration editor..."
        nano "$CONFIG_FILE"
    else
        echo "The current configuration will be used."
    fi

    # Verify the configuration structure
    local required_keys=("Proxy" "ModbusServer" "Logging" "version")
    for key in "${required_keys[@]}"; do
        if ! grep -q "$key:" "$CONFIG_FILE"; then
            echo "Error: Key '$key' is missing in $CONFIG_FILE. Exiting."
            exit 1
        fi
    done
}

# Check for updates and re-execute the latest script version
update_and_execute_latest() {
    if [ "${SKIP_UPDATE_CHECK:-0}" -eq 1 ]; then
        return  # Skip update check if already verified
    fi

    echo "Checking for the latest version of the installation script..."
    if [ -d "$BASE_DIR/.git" ]; then
        echo "Updating repository..."
        git -C "$BASE_DIR" fetch
        git -C "$BASE_DIR" reset --hard origin/main
    else
        echo "Cloning repository..."
        git clone "$REPO_URL" "$BASE_DIR"
    fi

    # Check if the installation script was updated
    local current_hash new_hash
    current_hash=$(sha256sum "$INSTALL_SCRIPT" | awk '{print $1}')
    new_hash=$(git -C "$BASE_DIR" show origin/main:install.sh | sha256sum | awk '{print $1}')

    if [ "$current_hash" != "$new_hash" ]; then
        echo "Installation script has been updated. Restarting the new version..."
        SKIP_UPDATE_CHECK=1 exec bash "$INSTALL_SCRIPT" "$@"
    fi
}

# Verify the OS
check_os

# Check for updates and re-execute the latest version if necessary
update_and_execute_latest

# Start installation process
echo "Starting installation process..."

# Install dependencies
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git bc nano || { echo "Error installing dependencies. Exiting."; exit 1; }

# Create the base directory if it doesn't exist
if [ ! -d "$BASE_DIR" ]; then
    sudo mkdir -p "$BASE_DIR"
    sudo chown $USER:$USER "$BASE_DIR"
fi

# Set up Python environment and dependencies
VENV_DIR="$BASE_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

REQ_FILE="$BASE_DIR/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    echo "requirements.txt not found. Exiting."
    exit 1
fi
pip install -r "$REQ_FILE"

# Open configuration menu
config_menu

# Create a systemd service file
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
sudo bash -c "cat << EOF > $SERVICE_FILE
[Unit]
Description=Modbus TCP Proxy Service
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python3 $BASE_DIR/modbus_tcp_proxy.py
WorkingDirectory=$BASE_DIR
Restart=always
User=$USER
Environment=\"PYTHONUNBUFFERED=1\"

[Install]
WantedBy=multi-user.target
EOF"

# Restart the service
restart_service

# Display version and host information
display_info

echo "System name: $(hostname)"
