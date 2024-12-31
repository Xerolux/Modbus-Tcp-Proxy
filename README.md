# **Modbus TCP Proxy**

## **Overview**
This project provides a Modbus-TCP Proxy service that enables the management of Modbus communication over TCP. It supports dynamic configuration and is compatible with Debian 12 and Ubuntu 24.

## **Features**
- **Supports Modbus-TCP communication.**
- **Dynamic configuration management.**
- **Persistent connection to the Modbus server.**
- **Robust error handling and automatic reconnection.**
- **Systemd service support.**
- **Flexible logging with multiple levels and output options.**

## **System Requirements**
- **Operating System:** Debian 12 or Ubuntu 24
- **Python:** Version 3.7 or newer

---

## Installation

You can install and configure the Modbus TCP Proxy using the provided `install.sh` script or manually. This guide covers both methods.

---

### Installation via `install.sh`

1. **Run the Installation Script**:
   ```bash
   curl -s https://raw.githubusercontent.com/Xerolux/Modbus-Tcp-Proxy/main/install.sh | sudo bash
   ```
   Or download it directly:
   [Download install.sh](https://raw.githubusercontent.com/Xerolux/Modbus-Tcp-Proxy/main/install.sh)

2. **Provide Configuration**:
   Create a configuration file at `/etc/Modbus-Tcp-Proxy/config.yaml`. See the example configuration below.

3. **Start the Proxy Service**:
   The script sets up a systemd service. Start it using:
   ```bash
   sudo systemctl start modbus_proxy.service
   ```

4. **Enable Service on Boot**:
   ```bash
   sudo systemctl enable modbus_proxy.service
   ```

---

### Manual Installation

1. **Install Dependencies**:
   ```bash
   sudo apt update && sudo apt install -y python3 python3-pip python3-venv git nano bc
   ```

2. **Clone the Repository**:
   ```bash
   git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git /opt/Modbus-Tcp-Proxy
   ```

3. **Set Up Python Environment**:
   ```bash
   cd /opt/Modbus-Tcp-Proxy
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Create Configuration File**:
   ```bash
   sudo mkdir -p /etc/Modbus-Tcp-Proxy
   nano /etc/Modbus-Tcp-Proxy/config.yaml
   ```
   Use the example configuration below.

5. **Run the Proxy**:
   ```bash
   python3 modbus_tcp_proxy.py --config /etc/Modbus-Tcp-Proxy/config.yaml
   ```

---

## Configuration File (`config.yaml`)

The configuration file defines the proxy settings, logging options, and Modbus server details. Below is an example:

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

### Configuration Parameters

- **Proxy**:
  - `ServerHost`: The IP address where the proxy server listens for incoming connections.
  - `ServerPort`: The port number for the proxy server.
- **ModbusServer**:
  - `ModbusServerHost`: The IP address of the Modbus server.
  - `ModbusServerPort`: The port number of the Modbus server.
  - `ConnectionTimeout`: Timeout in seconds for the Modbus server connection.
  - `DelayAfterConnection`: Delay in seconds after establishing a connection.
- **Logging**:
  - `Enable`: Enable or disable logging.
  - `LogFile`: Path to the log file.
  - `LogLevel`: Logging level (e.g., DEBUG, INFO, WARNING, ERROR).
- **Server**:
  - `MaxQueueSize`: Maximum size of the request queue.
  - `MaxWorkers`: Maximum number of concurrent threads.

---

## Service Management

The installation script sets up a `systemd` service named `modbus_proxy.service`. Below are common commands to manage the service:

- **Start Service**:
  ```bash
  sudo systemctl start modbus_proxy.service
  ```

- **Stop Service**:
  ```bash
  sudo systemctl stop modbus_proxy.service
  ```

- **Restart Service**:
  ```bash
  sudo systemctl restart modbus_proxy.service
  ```

- **Enable Service on Boot**:
  ```bash
  sudo systemctl enable modbus_proxy.service
  ```

- **Check Service Status**:
  ```bash
  sudo systemctl status modbus_proxy.service
  ```

---

## Logs

Logs are stored at the path specified in the configuration file (default: `/var/log/modbus_proxy.log`). You can view the logs using:

```bash
sudo tail -f /var/log/modbus_proxy.log
```

---

## Additional Notes

- Ensure that the Python virtual environment (`venv`) is activated when running the server manually.
- Keep the `config.yaml` file updated for any changes to the proxy or Modbus server.
- The server automatically handles reconnections to the Modbus server in case of a disconnect.

## **Libraries Used**
This project uses the following Python libraries:

- **pymodbus**: For Modbus-TCP communication ([PyPI Link](https://pypi.org/project/pymodbus/))
- **PyYAML**: For loading and processing YAML configuration files ([PyPI Link](https://pypi.org/project/PyYAML/))
- **logging**: Built-in Python library for logging
- **queue**: Built-in Python library for thread-safe management
- **socket**: Built-in Python library for network operations
- **threading**: Built-in Python library for multithreading

The required libraries are automatically installed via the installation script. For manual installation, use:

```bash
pip install -r /opt/Modbus-Tcp-Proxy/requirements.txt
```

## Supporting this Integration

If you'd like to support this integration or show your appreciation, you can:

<a href="https://www.buymeacoffee.com/xerolux" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;"></a>

## **License**
This project is licensed under the **MIT License**. For more details, see the [`LICENSE`](LICENSE) file.

## **Support**
If you have questions or encounter issues, please open an [issue on GitHub](https://github.com/Xerolux/Modbus-Tcp-Proxy/issues).

