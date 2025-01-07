#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Variables
REPO_URL="https://github.com/Xerolux/Modbus-Tcp-Proxy.git"
BASE_DIR="/opt/Modbus-Tcp-Proxy"
CONFIG_DIR="/etc/Modbus-Tcp-Proxy"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
SERVICE_NAME="modbus_proxy.service"

# Ensure configuration file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found at $CONFIG_FILE."
    echo "Please create the 'config.yaml' file before proceeding."
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

# Clone or update repository
if [ -d "$BASE_DIR/.git" ]; then
    echo "Updating repository..."
    git -C "$BASE_DIR" pull
else
    echo "Cloning repository..."
    sudo git clone "$REPO_URL" "$BASE_DIR"
    sudo chown -R $USER:$USER "$BASE_DIR"
fi

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv "$BASE_DIR/venv"
source "$BASE_DIR/venv/bin/activate"
pip install -r "$BASE_DIR/requirements.txt"

# Create systemd service file
echo "Creating systemd service..."
sudo tee /etc/systemd/system/$SERVICE_NAME > /dev/null <<EOF
[Unit]
Description=Modbus TCP Proxy Service
After=network.target

[Service]
ExecStart=$BASE_DIR/venv/bin/python3 $BASE_DIR/modbus_tcp_proxy.py --config $CONFIG_FILE
WorkingDirectory=$BASE_DIR
Restart=always
User=$USER
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

# Start and enable the service
echo "Starting and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

# Display success message
echo "Installation completed successfully!"
echo "Service: $SERVICE_NAME is running."
echo "Edit configuration at: $CONFIG_FILE if necessary."
