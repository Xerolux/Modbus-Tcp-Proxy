# Modbus TCP Proxy

## Overview
This project provides a Modbus TCP Proxy service that enables the management of Modbus communication over TCP. It supports dynamic configuration, robust logging, and is compatible with Debian 12 and Ubuntu 24. The setup is fully managed using a `Makefile`, which simplifies building, installing, running, updating, and packaging.

## Features
- Supports Modbus-TCP communication
- Dynamic YAML-based configuration
- Persistent connection to the Modbus server
- Automatic reconnection and robust error handling
- Systemd service integration
- Flexible logging (console and file)
- Easy install/update via `make`
- Package support: `.deb` and Docker

## System Requirements
- **Operating System:** Debian 12 or Ubuntu 24
- **Python:** 3.7 or newer

## Installation with Make
All project operations are handled through a `Makefile`.

### 💡 Common Commands:
```bash
make install          # First-time setup
make update           # Pull latest version + update dependencies
make restart          # Restart the systemd service
make logs             # Show live logs
make backup-config    # Backup the config file
make uninstall        # Remove everything except config
```

## Configuration
Create your configuration at:
```bash
/etc/Modbus-Tcp-Proxy/config.yaml
```

### Example:
```yaml
Proxy:
  ServerHost: "0.0.0.0"
  ServerPort: 502

ModbusServer:
  ModbusServerHost: "192.168.1.100"
  ModbusServerPort: 502
  ConnectionTimeout: 10
  DelayAfterConnection: 0.5

Logging:
  Enable: true
  LogFile: "/var/log/modbus_proxy.log"
  LogLevel: "INFO"

Server:
  MaxQueueSize: 100
  MaxWorkers: 8
```

### Parameters
- **Proxy:** Listen address and port for incoming clients
- **ModbusServer:** Target Modbus server connection parameters
- **Logging:** Logging control and log level
- **Server:** Thread pool and request queue configuration

## Service Management (Systemd)
The `make install` command sets up a systemd service named `modbus_proxy.service`. You can manage it using:
```bash
sudo systemctl start modbus_proxy.service
sudo systemctl stop modbus_proxy.service
sudo systemctl restart modbus_proxy.service
sudo systemctl enable modbus_proxy.service
sudo systemctl status modbus_proxy.service
```

## Logs
```bash
sudo tail -f /var/log/modbus_proxy.log
```

## Docker Usage
A `Dockerfile` is provided to run the proxy in a container.

### Build the image:
```bash
docker build -t modbus-proxy .
```

### Run the container:
```bash
docker run -d \
  --name modbus-proxy \
  -p 502:502 \
  -v /your/config/path/config.yaml:/etc/Modbus-Tcp-Proxy/config.yaml \
  modbus-proxy
```

## .deb Package
This project includes support for packaging into a `.deb` file.

### Structure:
```
debian/
├── DEBIAN/control
├── opt/Modbus-Tcp-Proxy/...
└── etc/Modbus-Tcp-Proxy/config.yaml
```

### Build .deb package:
```bash
dpkg-deb --build debian build/modbus-tcp-proxy.deb
```

### Install:
```bash
sudo dpkg -i build/modbus-tcp-proxy.deb
```

## Development Notes
- The proxy uses a persistent socket to the Modbus server and handles multiple client connections.
- Automatic reconnection ensures high availability.
- Thread-safe queue and thread pool handle incoming requests efficiently.

## Libraries Used
- `pymodbus` – Modbus TCP communication
- `PyYAML` – YAML config loader
- `cerberus` – Configuration schema validation
- Built-in: `logging`, `queue`, `socket`, `threading`

Install manually with:
```bash
pip install -r requirements.txt
```

## Like the Project?

If you'd like to support this integration or show your appreciation, you can:

<a href="https://www.buymeacoffee.com/xerolux" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;"></a>

## License
MIT License – see LICENSE file.

## Support
For questions or issues, open a [GitHub Issue](https://github.com/Xerolux/Modbus-Tcp-Proxy/issues).

