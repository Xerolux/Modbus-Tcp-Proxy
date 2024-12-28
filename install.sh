#!/bin/bash

# Update and install dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# Check for existing installation and update if necessary
if [ -d "/opt/Modbus-Tcp-Proxy" ]; then
    echo "Checking for updates..."
    cd /opt/Modbus-Tcp-Proxy
    git fetch
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})

    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Updating repository..."
        git pull
        if [ $? -ne 0 ]; then
            echo "Git pull failed. Exiting."
            exit 1
        fi
    else
        echo "Already up-to-date. Exiting installation."
        exit 0
    fi
else
    echo "Cloning repository..."
    git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git /opt/Modbus-Tcp-Proxy
    if [ $? -ne 0 ]; then
        echo "Git clone failed. Exiting."
        exit 1
    fi
    cd /opt/Modbus-Tcp-Proxy
fi

# Check Python version
python3 -c "import sys; assert sys.version_info >= (3, 7), 'Python 3.7 or newer is required.'"
if [ $? -ne 0 ]; then
    echo "Unsupported Python version. Please install Python 3.7 or newer."
    exit 1
fi

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Virtual environment activation failed. Exiting."
    exit 1
fi

# Install Python dependencies
if [ ! -f requirements.txt ]; then
    echo "requirements.txt not found. Exiting."
    deactivate
    exit 1
fi
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install dependencies. Exiting."
    deactivate
    exit 1
fi

# Configuration menu
echo "Starting configuration menu..."
read -p "Enter Proxy Server Host (default: 0.0.0.0): " proxy_host
proxy_host=${proxy_host:-0.0.0.0}

read -p "Enter Proxy Server Port (default: 502): " proxy_port
proxy_port=${proxy_port:-502}

read -p "Enter Modbus Server Host (e.g., 192.168.1.100): " modbus_host
read -p "Enter Modbus Server Port (default: 502): " modbus_port
modbus_port=${modbus_port:-502}

read -p "Enter Connection Timeout in seconds (default: 10): " connection_timeout
connection_timeout=${connection_timeout:-10}

read -p "Enter Delay After Connection in seconds (default: 0.5): " delay_after
delay_after=${delay_after:-0.5}

read -p "Enable Logging? (yes/no, default: yes): " enable_logging
enable_logging=${enable_logging:-yes}
if [ "$enable_logging" == "yes" ]; then
    enable_logging=true
    read -p "Enter Log File Path (default: /var/log/modbus_proxy.log): " log_file
    log_file=${log_file:-/var/log/modbus_proxy.log}

    read -p "Enter Log Level (INFO/DEBUG/ERROR, default: INFO): " log_level
    log_level=${log_level:-INFO}
else
    enable_logging=false
fi

# Ensure log directory exists
if [ "$enable_logging" == "true" ]; then
    log_dir=$(dirname "$log_file")
    if [ ! -d "$log_dir" ]; then
        echo "Log directory $log_dir not found. Creating it..."
        sudo mkdir -p "$log_dir"
        sudo chown $USER:$USER "$log_dir"
    fi
    if [ ! -w "$log_dir" ]; then
        echo "No write permissions for $log_dir. Adjusting permissions..."
        sudo chmod u+w "$log_dir"
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
sudo systemctl daemon-reload
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
