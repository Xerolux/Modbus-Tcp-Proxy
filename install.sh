#!/bin/bash

# Update and install dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# Clone the repository
echo "Cloning repository..."
git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git /opt/Modbus-Tcp-Proxy
cd /opt/Modbus-Tcp-Proxy

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Copy example config
cp config.example.yaml config.yaml

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

echo "\nInstallation complete! Edit 'config.yaml' to configure the proxy and manage the service using systemd."
