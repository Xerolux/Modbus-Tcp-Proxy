# **Modbus TCP Proxy**

## **Overview**
This project provides a Modbus-TCP Proxy service that enables the management of Modbus communication over TCP. It supports dynamic configuration and is compatible with Debian 12 and Ubuntu 24.

## **Features**
- **Supports Modbus-TCP communication.**
- **Dynamic configuration management.**
- **Automatic updates via Git.**
- **Systemd service support.**

## **System Requirements**
- **Operating System:** Debian 12 or Ubuntu 24
- **Python:** Version 3.7 or newer

## **Installation**
### **Automatic Installation**
To automatically install the Modbus-TCP Proxy, run the following commands:

```bash
wget -O install.sh https://raw.githubusercontent.com/Xerolux/Modbus-Tcp-Proxy/main/install.sh
bash install.sh
```

The script performs all necessary steps, including:
- **Installing dependencies**
- **Setting up a virtual environment**
- **Configuring the Systemd service**
- **Starting the service**

### **Manual Installation**
If you prefer manual installation, follow these steps:

#### **1. Install Dependencies**
Run the following commands to install the required packages:
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git bc
```

#### **2. Clone Repository**
Clone the Git repository into the `/opt/Modbus-Tcp-Proxy` directory:
```bash
git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git /opt/Modbus-Tcp-Proxy
```

#### **3. Run the Installation Script**
Execute the installation script:
```bash
bash /opt/Modbus-Tcp-Proxy/install.sh
```
The script installs dependencies, creates a virtual environment, and sets up the Systemd service.

## **Configuration**
The configuration file is located at `config.yaml` in the `/opt/Modbus-Tcp-Proxy` directory.

### **Example Configuration**
```yaml
version: 0.0.4
Proxy:
  ServerHost: 0.0.0.0
  ServerPort: 5020
ModbusServer:
  ModbusServerHost: 192.168.178.196
  ModbusServerPort: 5020
  ConnectionTimeout: 10
  DelayAfterConnection: 0.5
Logging:
  Enable: true
  LogFile: /var/log/modbus_proxy.log
  LogLevel: INFO
```

- **Proxy.ServerHost**: The address the proxy binds to.
- **Proxy.ServerPort**: The port the proxy listens on.
- **ModbusServer.ModbusServerHost**: The target address of the Modbus server.
- **ModbusServer.ModbusServerPort**: The target port of the Modbus server.
- **Logging.LogFile**: The path to the log file.

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

## **Usage**
### **Start the Service**
The Systemd service is automatically started after installation. To manage it manually:

**Start the service:**
```bash
sudo systemctl start modbus_proxy.service
```

**Stop the service:**
```bash
sudo systemctl stop modbus_proxy.service
```

**Check service status:**
```bash
sudo systemctl status modbus_proxy.service
```

### **View Logs**
Logs are located by default at `/var/log/modbus_proxy.log`.

## **Update**
The installation script automatically checks for updates in the Git repository and applies them. Simply run the installation script again:
```bash
bash /opt/Modbus-Tcp-Proxy/install.sh
```

## **License**
This project is licensed under the **MIT License**. For more details, see the [`LICENSE`](LICENSE) file.

## **Support**
If you have questions or encounter issues, please open an [issue on GitHub](https://github.com/Xerolux/Modbus-Tcp-Proxy/issues).
