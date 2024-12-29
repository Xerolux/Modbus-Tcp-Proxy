#!/bin/bash

# Update and install dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git || { echo "Failed to install dependencies. Exiting."; exit 1; }

# Create base directory if it does not exist
if [ ! -d "/opt/Modbus-Tcp-Proxy" ]; then
    echo "Creating base directory /opt/Modbus-Tcp-Proxy..."
    sudo mkdir -p /opt/Modbus-Tcp-Proxy || { echo "Failed to create base directory. Exiting."; exit 1; }
    sudo chown $USER:$USER /opt/Modbus-Tcp-Proxy || { echo "Failed to set permissions on base directory. Exiting."; exit 1; }
fi

# Check for existing installation and update if necessary
if [ -d "/opt/Modbus-Tcp-Proxy/.git" ]; then
    echo "Checking for updates..."
    cd /opt/Modbus-Tcp-Proxy
    git fetch
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})

    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Updating repository and overwriting local changes..."
        git reset --hard @{u} || { echo "Git reset failed. Exiting."; exit 1; }
        git pull || { echo "Git pull failed. Exiting."; exit 1; }
    else
        echo "Already up-to-date. Exiting installation."
        exit 0
    fi
else
    echo "Cloning repository..."
    git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git /opt/Modbus-Tcp-Proxy || { echo "Git clone failed. Exiting."; exit 1; }
    cd /opt/Modbus-Tcp-Proxy
fi

# Check Python version
python3 -c "import sys; assert sys.version_info >= (3, 7), 'Python 3.7 or newer is required.'" || { echo "Unsupported Python version. Exiting."; exit 1; }

# Create virtual environment
if [ ! -d "/opt/Modbus-Tcp-Proxy/venv" ]; then
    python3 -m venv /opt/Modbus-Tcp-Proxy/venv || { echo "Failed to create virtual environment. Exiting."; exit 1; }
    echo "Virtual environment created."
else
    echo "Virtual environment already exists. Skipping creation."
fi
source /opt/Modbus-Tcp-Proxy/venv/bin/activate || { echo "Failed to activate virtual environment. Exiting."; exit 1; }

# Install Python dependencies
if [ ! -f /opt/Modbus-Tcp-Proxy/requirements.txt ]; then
    echo "requirements.txt not found in /opt/Modbus-Tcp-Proxy. Exiting."
    deactivate
    exit 1
fi
pip install -r requirements.txt || { echo "Failed to install Python dependencies. Exiting."; deactivate; exit 1; }

# Check if the proxy port is in use and kill the process if needed
if lsof -i :5020 > /dev/null; then
    echo "Port 5020 is in use. Attempting to free it..."
    pid=$(lsof -t -i :5020)
    if [ -n "$pid" ]; then
        echo "Killing process $pid that is using port 5020..."
        sudo kill -9 $pid || { echo "Failed to kill process $pid. Exiting."; exit 1; }
    fi
else
    echo "Port 5020 is free."
fi

# Configuration menu
echo "Starting configuration menu..."
read -p "Enter Proxy Server Host (default: 0.0.0.0): " proxy_host
proxy_host=${proxy_host:-0.0.0.0}

if [[ ! $proxy_host =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ && $proxy_host != "0.0.0.0" ]]; then
    echo "Invalid Proxy Server Host. Exiting."
    exit 1
fi

read -p "Enter Proxy Server Port (default: 5020): " proxy_port
proxy_port=${proxy_port:-5020}
if ! [[ $proxy_port =~ ^[0-9]+$ ]] || [ $proxy_port -le 0 ] || [ $proxy_port -gt 65535 ]; then
    echo "Invalid Proxy Server Port. Exiting."
    exit 1
fi

read -p "Enter Modbus Server Host (default: 192.168.178.197): " modbus_host
modbus_host=${modbus_host:-192.168.178.197}
if [[ ! $modbus_host =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    echo "Invalid Modbus Server Host. Exiting."
    exit 1
fi

read -p "Enter Modbus Server Port (default: 1502): " modbus_port
modbus_port=${modbus_port:-1502}
if ! [[ $modbus_port =~ ^[0-9]+$ ]] || [ $modbus_port -le 0 ] || [ $modbus_port -gt 65535 ]; then
    echo "Invalid Modbus Server Port. Exiting."
    exit 1
fi

read -p "Enter Connection Timeout in seconds (default: 10): " connection_timeout
connection_timeout=${connection_timeout:-10}
if ! [[ $connection_timeout =~ ^[0-9]+(\.[0-9]+)?$ ]] || (( $(echo "$connection_timeout <= 0" | bc -l) )); then
    echo "Invalid Connection Timeout. Exiting."
    exit 1
fi

read -p "Enter Delay After Connection in seconds (default: 0.5): " delay_after
delay_after=${delay_after:-0.5}
if ! [[ $delay_after =~ ^[0-9]+(\.[0-9]+)?$ ]] || (( $(echo "$delay_after < 0" | bc -l) )); then
    echo "Invalid Delay After Connection. Exiting."
    exit 1
fi

read -p "Enable Logging? (yes/no, default: yes): " enable_logging
enable_logging=${enable_logging:-yes}
if [[ $enable_logging != "yes" && $enable_logging != "no" ]]; then
    echo "Invalid input for logging. Exiting."
    exit 1
fi
if [ "$enable_logging" == "yes" ]; then
    enable_logging=true
    read -p "Enter Log File Path (default: /var/log/modbus_proxy.log): " log_file
    log_file=${log_file:-/var/log/modbus_proxy.log}

    read -p "Enter Log Level (INFO/DEBUG/ERROR, default: INFO): " log_level
    log_level=${log_level:-INFO}
    if [[ ! $log_level =~ ^(INFO|DEBUG|ERROR)$ ]]; then
        echo "Invalid Log Level. Exiting."
        exit 1
    fi
else
    enable_logging=false
fi

# Ensure log directory exists
if [ "$enable_logging" == "true" ]; then
    log_dir=$(dirname "$log_file")
    if [ ! -d "$log_dir" ]; then
        echo "Log directory $log_dir not found. Creating it..."
        sudo mkdir -p "$log_dir" || { echo "Failed to create log directory. Exiting."; exit 1; }
        sudo chown $USER:$USER "$log_dir" || { echo "Failed to set permissions on log directory. Exiting."; exit 1; }
    fi
    if [ ! -w "$log_dir" ]; then
        echo "No write permissions for $log_dir. Adjusting permissions..."
        sudo chmod u+w "$log_dir" || { echo "Failed to adjust permissions on log directory. Exiting."; exit 1; }
    fi
fi

# Create config.yaml
cat << EOF > config.yaml
Proxy:
  ServerHost: $proxy_host
  ServerPort: $proxy_port

ModbusServer:
  ModbusServerHost: $modbus_host
  ModbusServerPort: $modbus_port
  ConnectionTimeout: $connection_timeout
  DelayAfterConnection: $delay_after

Logging:
  Enable: $enable_logging
EOF

if [ "$enable_logging" == "true" ]; then
  cat << EOF >> config.yaml
  LogFile: $log_file
  LogLevel: $log_level
EOF
fi

echo "Configuration saved to config.yaml."

# Create systemd service file
echo "Creating systemd service file..."
sudo bash -c 'cat << EOF > /etc/systemd/system/modbus_proxy.service
[Unit]
Description=Modbus TCP Proxy Service
After=network.target

[Service]
ExecStart=/opt/Modbus-Tcp-Proxy/venv/bin/python3 /opt/Modbus-Tcp-Proxy/modbus_tcp_proxy.py
WorkingDirectory=/opt/Modbus-Tcp-Proxy
Restart=always
User=$USER

[Install]
WantedBy=multi-user.target
EOF'

# Reload systemd and enable service
sudo systemctl daemon-reload || { echo "Failed to reload systemd daemon. Exiting."; exit 1; }
if ! sudo systemctl enable modbus_proxy.service; then
    echo "Failed to enable systemd service. Exiting."
    exit 1
fi

if ! sudo systemctl start modbus_proxy.service; then
    echo "Failed to start systemd service. Exiting."
    exit 1
fi

# Completion message
echo "\nInstallation complete! Edit 'config.yaml' to reconfigure the proxy. Remember to restart the service using 'sudo systemctl restart modbus_proxy.service' after changes."
