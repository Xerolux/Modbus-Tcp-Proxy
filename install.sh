#!/bin/bash

set -e

# Update and install dependencies
echo "Updating system and installing dependencies..."
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git bc || { echo "Failed to install dependencies. Exiting."; exit 1; }

# Create base directory
BASE_DIR="/opt/Modbus-Tcp-Proxy"
if [ ! -d "$BASE_DIR" ]; then
    echo "Creating base directory at $BASE_DIR..."
    sudo mkdir -p "$BASE_DIR"
    sudo chown $USER:$USER "$BASE_DIR"
else
    echo "Base directory already exists at $BASE_DIR."
fi

# Clone or update repository
REPO_URL="https://github.com/Xerolux/Modbus-Tcp-Proxy.git"
if [ -d "$BASE_DIR/.git" ]; then
    echo "Updating repository..."
    cd "$BASE_DIR"
    git fetch && git reset --hard origin/main || { echo "Git update failed. Exiting."; exit 1; }
else
    echo "Cloning repository from $REPO_URL..."
    git clone "$REPO_URL" "$BASE_DIR" || { echo "Git clone failed. Exiting."; exit 1; }
    cd "$BASE_DIR"
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

# Check and free proxy port if necessary
PROXY_PORT=5020
if lsof -i :"$PROXY_PORT" > /dev/null; then
    echo "Port $PROXY_PORT is in use. Attempting to free it..."
    pid=$(lsof -t -i :"$PROXY_PORT")
    if [ -n "$pid" ]; then
        sudo kill -9 "$pid" || { echo "Failed to free port $PROXY_PORT. Exiting."; exit 1; }
    fi
else
    echo "Port $PROXY_PORT is free."
fi

# Configuration
read -p "Enter Proxy Server Host (default: 0.0.0.0): " proxy_host
proxy_host=${proxy_host:-0.0.0.0}
if [[ ! $proxy_host =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ && $proxy_host != "0.0.0.0" ]]; then
    echo "Invalid Proxy Server Host. Exiting."
    exit 1
fi

# Similar validation steps for other inputs...

# Create configuration file
CONFIG_FILE="$BASE_DIR/config.yaml"
cat << EOF > "$CONFIG_FILE"
Proxy:
  ServerHost: $proxy_host
  ServerPort: $PROXY_PORT
# Additional configuration goes here...
EOF
echo "Configuration saved to $CONFIG_FILE."

# Create systemd service file
SERVICE_FILE="/etc/systemd/system/modbus_proxy.service"
echo "Creating systemd service file..."
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

# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable modbus_proxy.service
sudo systemctl start modbus_proxy.service

echo "Installation and configuration complete. Service is running."
