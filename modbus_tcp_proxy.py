"""
Modbus TCP Proxy Server

This script implements a Modbus TCP Proxy Server with robust error handling and persistent connections.
Features include:
- Persistent Modbus server connection.
- Multi-threaded request handling.
- Configuration via YAML file.
- Logging with adjustable verbosity.
- Watchdog for monitoring connections and restarting when necessary.

Author: [Xerolux]
Date: [31.12.2024]
"""

import argparse
import os
import queue
import threading
import time
import logging
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import yaml
from pymodbus.client import ModbusTcpClient

# Global variables for shared components
server_socket = None
persistent_client = None
watchdog = None

@dataclass
class ModbusConfig:
    """Container for Modbus server configuration."""
    host: str
    port: int
    timeout: int
    delay: float

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
            except Exception as exc:
                self.logger.error("Connection error: %s. Retrying...", exc)
                time.sleep(0.5)

    def close(self):
        """
        Close the Modbus connection.
        """
        if self.client:
            self.client.close()
            self.logger.info("Modbus connection closed.")

def handle_client(client_socket, client_address, request_queue, logger):
    """
    Handle a client connection.

    Args:
        client_socket (socket.socket): Socket for client communication.
        client_address (tuple): Client's IP address and port.
        request_queue (queue.Queue): Queue for client requests.
        logger (logging.Logger): Logger instance for logging.
    """
    try:
        logger.info("New client connected: %s", client_address)
        while True:
            data = client_socket.recv(1024)
            if not data:
                logger.info("Client disconnected: %s", client_address)
                break
            request_queue.put((data, client_socket))
    except Exception as exc:
        logger.error("Error with client %s: %s", client_address, exc)
    finally:
        client_socket.close()
        logger.info("Socket for %s closed", client_address)

def process_requests(request_queue, persistent_client, logger):
    """
    Process requests to the Modbus server using a persistent connection.

    Args:
        request_queue (queue.Queue): Queue for client requests.
        persistent_client (PersistentModbusClient): Persistent Modbus client.
        logger (logging.Logger): Logger instance for logging.
    """
    while True:
        try:
            data, client_socket = request_queue.get()
            if client_socket.fileno() == -1:
                logger.error("Client socket is closed. Skipping request.")
                continue
            try:
                persistent_client.connect()
                client_socket.sendall(data)
            except Exception as exc:
                logger.error("Error processing request: %s", exc)
                client_socket.close()
        except Exception as exc:
            logger.error("Error processing queue: %s", exc)

class ModbusWatchdog(threading.Thread):
    """Thread-based watchdog for monitoring Modbus connectivity."""

    def __init__(self, persistent_client, max_retries, restart_callback, logger):
        """
        Initialize the Modbus Watchdog.

        Args:
            persistent_client (PersistentModbusClient): Modbus client instance.
            max_retries (int): Maximum retries before restart.
            restart_callback (function): Callback to restart the proxy.
            logger (logging.Logger): Logger instance for logging.
        """
        super().__init__()
        self.persistent_client = persistent_client
        self.max_retries = max_retries
        self.restart_callback = restart_callback
        self.logger = logger
        self.stop_event = threading.Event()

    def run(self):
        """
        Main loop for monitoring Modbus connection and triggering restarts.
        """
        retries = 0
        while not self.stop_event.is_set():
            try:
                if self.persistent_client.client and self.persistent_client.client.is_socket_open():
                    self.logger.info("Watchdog: Modbus connection is active.")
                    retries = 0
                else:
                    retries += 1
                    self.logger.warning(
                        "Watchdog: Modbus connection failed. Attempt %d of %d",
                        retries,
                        self.max_retries,
                    )
                    self.persistent_client.connect()

                if retries >= self.max_retries:
                    self.logger.error("Watchdog: Max retries reached. Restarting.")
                    self.restart_callback()
                    retries = 0
            except Exception as exc:
                self.logger.error("Watchdog error: %s", exc)

            time.sleep(5)

    def stop(self):
        """
        Stop the watchdog thread.
        """
        self.stop_event.set()

def restart_proxy():
    """
    Restart the proxy application.
    """
    logging.info("Restarting the proxy...")
    cleanup_resources()
    os.execv(sys.executable, ['python'] + sys.argv)

def cleanup_resources():
    """
    Cleanup resources such as sockets and connections before restarting.
    """
    logging.info("Cleaning up resources...")
    global server_socket, persistent_client, watchdog
    if watchdog:
        watchdog.stop()
    if persistent_client:
        persistent_client.close()
    if server_socket:
        server_socket.close()
        logging.info("Server socket closed.")

def start_server(config):
    """
    Start the Modbus TCP Proxy Server.

    Args:
        config (dict): Configuration settings.
    """
    global server_socket, persistent_client, watchdog

    logger = init_logger(config)
    request_queue = queue.Queue()

    modbus_config = ModbusConfig(
        host=config["ModbusServer"]["ModbusServerHost"],
        port=int(config["ModbusServer"]["ModbusServerPort"]),
        timeout=config["ModbusServer"].get("ConnectionTimeout", 10),
        delay=config["ModbusServer"].get("DelayAfterConnection", 0.5),
    )

    persistent_client = PersistentModbusClient(modbus_config, logger)
    persistent_client.connect()

    watchdog = ModbusWatchdog(
        persistent_client=persistent_client,
        max_retries=3,
        restart_callback=restart_proxy,
        logger=logger,
    )
    watchdog.start()

    with ThreadPoolExecutor(max_workers=10) as executor:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"]))
        server_socket.listen(5)
        logger.info(
            "Proxy server listening on %s:%d",
            config["Proxy"]["ServerHost"],
            config["Proxy"]["ServerPort"],
        )

        executor.submit(process_requests, request_queue, persistent_client, logger)

        try:
            while True:
                client_socket, client_address = server_socket.accept()
                executor.submit(
                    handle_client, client_socket, client_address, request_queue, logger
                )
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
        except Exception as exc:
            logger.error("Server error: %s", exc)
        finally:
            cleanup_resources()

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
    finally:
        cleanup_resources()
