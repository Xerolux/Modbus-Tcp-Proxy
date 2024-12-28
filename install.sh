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
    else
        echo "Already up-to-date. Exiting installation."
        exit 0
    fi
else
    echo "Cloning repository..."
    git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git /opt/Modbus-Tcp-Proxy
    cd /opt/Modbus-Tcp-Proxy
fi

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

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
    read -p "Enter Log File Path (default: /var/log/modbus_proxy.log): " log_file
    log_file=${log_file:-/var/log/modbus_proxy.log}

    read -p "Enter Log Level (INFO/DEBUG/ERROR, default: INFO): " log_level
    log_level=${log_level:-INFO}
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

if [ "$enable_logging" == "yes" ]; then
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
ExecStart=/usr/bin/python3 /opt/Modbus-Tcp-Proxy/modbus_tcp_proxy.py
WorkingDirectory=/opt/Modbus-Tcp-Proxy
Restart=always
User=$USER

[Install]
WantedBy=multi-user.target
EOF'

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable modbus_proxy.service

# Start the service
sudo systemctl start modbus_proxy.service

echo "\nInstallation complete! Edit 'config.yaml' to reconfigure the proxy and manage the service using systemd."
