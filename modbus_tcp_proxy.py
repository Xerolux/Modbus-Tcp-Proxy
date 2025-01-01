"""
Modbus TCP Proxy Server with Whitelist and Read/Write Control

This script implements a Modbus TCP Proxy Server with enhanced error handling, whitelist for clients, and 
optional Read/Write control.

Features include:
1. Persistent Modbus server connection.
2. Multi-threaded request handling.
3. Configuration via YAML file.
4. Logging with adjustable verbosity.
5. Whitelist for allowed clients.
6. Optional Read-Only or Read/Write control.

Author: [Xerolux]
Date: [01.01.2025]
"""

import argparse
import queue
import time
import logging
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import yaml
from pymodbus.client import ModbusTcpClient

# Global variables for shared components
SERVER_SOCKET = None
PERSISTENT_CLIENT = None
WATCHDOG = None
WHITELIST = set()

@dataclass
class ModbusConfig:
    """Container for Modbus server configuration."""
    host: str
    port: int
    timeout: int
    delay: float
    read_only: bool

def load_config(config_path):
    """
    Load and validate the YAML configuration file.

    Args:
        config_path (str): Path to the YAML configuration file.

    Returns:
        dict: The parsed and validated configuration settings.

    Raises:
        ValueError: If the configuration contains invalid values.
    """
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    # Validate server host and port
    ipaddress.IPv4Address(config["Proxy"]["ServerHost"])
    if not 0 < config["Proxy"]["ServerPort"] < 65536:
        raise ValueError(f"Invalid port: {config['Proxy']['ServerPort']}")

    return config

def load_whitelist(whitelist_file):
    """
    Load the whitelist of allowed IPv4 addresses from a file.

    Args:
        whitelist_file (str): Path to the whitelist file.

    Returns:
        set: A set of allowed IPv4 addresses.
    """
    try:
        with open(whitelist_file, "r", encoding="utf-8") as file:
            addresses = {line.strip() for line in file if line.strip()}
            for ip in addresses:
                ipaddress.IPv4Address(ip)
            return addresses
    except Exception as exc:
        logging.error("Failed to load whitelist: %s", exc)
        return set()

def is_client_allowed(client_address):
    """
    Check if the client is allowed to connect based on the whitelist.

    Args:
        client_address (tuple): Client's IP address and port.

    Returns:
        bool: True if the client is allowed, False otherwise.
    """
    client_ip = client_address[0]
    return client_ip in WHITELIST

def init_logger(config):
    """
    Initialize the logging system based on the configuration.

    Args:
        config (dict): Configuration settings.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger()
    logger.setLevel(config["Logging"].get("LogLevel", "INFO").upper())

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # File logging
    if config["Logging"].get("Enable", False):
        file_handler = logging.FileHandler(
            config["Logging"].get("LogFile", "modbus_proxy.log")
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Console logging
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

class PersistentModbusClient:
    """Wrapper class for maintaining a persistent Modbus TCP connection."""

    def __init__(self, modbus_config, logger):
        """
        Initialize the persistent Modbus client.

        Args:
            modbus_config (ModbusConfig): Modbus server configuration.
            logger (logging.Logger): Logger instance for logging.
        """
        self.config = modbus_config
        self.logger = logger
        self.client = None

    def connect(self):
        """
        Establish or re-establish a connection to the Modbus server.

        Retries indefinitely until the connection is successful.
        """
        while not self.client or not self.client.is_socket_open():
            try:
                self.client = ModbusTcpClient(
                    host=self.config.host, port=self.config.port, timeout=self.config.timeout
                )
                if self.client.connect():
                    self.logger.info("Successfully connected to Modbus server.")
                    time.sleep(self.config.delay)
                else:
                    raise ConnectionError("Failed to connect to Modbus server.")
            except (ConnectionError, OSError) as exc:
                self.logger.error("Connection error: %s. Retrying...", exc)
                time.sleep(0.5)

    def close(self):
        """
        Close the Modbus connection.
        """
        if self.client:
            self.client.close()
            self.logger.info("Modbus connection closed.")

def is_read_request(data):
    """
    Check if the Modbus request is a read operation.

    Args:
        data (bytes): Modbus request data.

    Returns:
        bool: True if the request is a read operation, False otherwise.
    """
    READ_FUNCTION_CODES = {3, 4}  # Function codes for read operations
    try:
        function_code = data[7]  # Function code is the 8th byte in the Modbus TCP request
        return function_code in READ_FUNCTION_CODES
    except IndexError:
        return False

def handle_client(client_socket, client_address, request_queue, logger, security_config):
    """
    Handle a client connection with improved error handling.

    Args:
        client_socket (socket.socket): Socket for client communication.
        client_address (tuple): Client's IP address and port.
        request_queue (queue.Queue): Queue for client requests.
        logger (logging.Logger): Logger instance for logging.
        security_config (dict): Security settings from the configuration.
    """
    if security_config["EnableWhitelist"] and not is_client_allowed(client_address):
        logger.warning("Unauthorized client rejected: %s", client_address[0])
        client_socket.close()
        return

    try:
        logger.info("New client connected: %s", client_address)
        while True:
            try:
                data = client_socket.recv(1024)
                if not data:
                    logger.info("Client disconnected: %s", client_address)
                    break

                # Enforce read-only policy if configured
                if security_config["ReadOnly"] and not is_read_request(data):
                    logger.warning("Write request blocked from client: %s", client_address)
                    continue

                request_queue.put((data, client_socket))
            except (ConnectionResetError, BrokenPipeError) as exc:
                logger.error("Communication error with %s: %s", client_address, exc)
                break
    except OSError as exc:
        logger.error("Error with client %s: %s", client_address, exc)
    finally:
        try:
            client_socket.close()
        except OSError as exc:
            logger.error("Error closing socket for %s: %s", client_address, exc)
        logger.info("Socket for %s closed", client_address)

def process_requests(request_queue, persistent_client, logger):
    """
    Process requests with enhanced error handling.

    Args:
        request_queue (queue.Queue): Queue for client requests.
        persistent_client (PersistentModbusClient): Persistent Modbus client.
        logger (logging.Logger): Logger instance for logging.
    """
    while True:
        try:
            data, client_socket = request_queue.get()
            if client_socket.fileno() == -1:  # Check if socket is still valid
                logger.error("Client socket is closed. Skipping request.")
                continue

            try:
                persistent_client.connect()
                client_socket.sendall(data)
            except (BrokenPipeError, ConnectionResetError) as exc:
                logger.error("Error processing request: %s", exc)
                client_socket.close()
        except queue.Empty:
            logger.error("Queue is empty. Skipping request.")
        except OSError as exc:
            logger.error("Unexpected error processing queue: %s", exc)

def start_server(config):
    """
    Start the Modbus TCP Proxy Server.

    Args:
        config (dict): Configuration settings.
    """
    global SERVER_SOCKET, PERSISTENT_CLIENT, WHITELIST

    logger = init_logger(config)
    request_queue = queue.Queue()

    if config["Security"]["EnableWhitelist"]:
        WHITELIST = load_whitelist(config["Security"]["WhitelistFile"])
        logger.info("Whitelist loaded with %d allowed addresses.", len(WHITELIST))

    modbus_config = ModbusConfig(
        host=config["ModbusServer"]["ModbusServerHost"],
        port=int(config["ModbusServer"]["ModbusServerPort"]),
        timeout=config["ModbusServer"].get("ConnectionTimeout", 10),
        delay=config["ModbusServer"].get("DelayAfterConnection", 0.5),
        read_only=config["Security"].get("ReadOnly", False),
    )

    PERSISTENT_CLIENT = PersistentModbusClient(modbus_config, logger)
    PERSISTENT_CLIENT.connect()

    with ThreadPoolExecutor(max_workers=10) as executor:
        SERVER_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        SERVER_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        SERVER_SOCKET.bind((config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"]))
        SERVER_SOCKET.listen(5)
        logger.info(
            "Proxy server listening on %s:%d",
            config["Proxy"]["ServerHost"],
            config["Proxy"]["ServerPort"],
        )

        try:
            while True:
                client_socket, client_address = SERVER_SOCKET.accept()
                executor.submit(
                    handle_client, client_socket, client_address, request_queue, logger, config["Security"]
                )
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
        except OSError as exc:
            logger.error("Server error: %s", exc)
        finally:
            if SERVER_SOCKET:
                SERVER_SOCKET.close()
                logger.info("Server socket closed.")

def parse_arguments():
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Modbus TCP Proxy Server")
    parser.add_argument(
        "--config", required=True, help="Path to the configuration file (YAML format)"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    try:
        configuration = load_config(args.config)
        start_server(configuration)
    except FileNotFoundError as exc:
        print(f"Configuration file not found: {exc}")
    except ValueError as exc:
        print(f"Invalid configuration: {exc}")
    except OSError as exc:
        print(f"OS error: {exc}")
    except KeyboardInterrupt:
        print("Server shutdown requested by user.")
