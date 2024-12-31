"""
Modbus TCP Proxy Server with Persistent Connection

This module implements a proxy server for Modbus TCP requests
with a persistent connection to the Modbus server.
"""

import os
import queue
import threading
import time
import logging
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor
import yaml
from pymodbus.client import ModbusTcpClient


def load_config():
    """
    Loads and validates the configuration file.

    :return: A dictionary containing configuration settings.
    """
    with open("config.yaml", "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    try:
        ipaddress.IPv4Address(config["Proxy"]["ServerHost"])
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"Invalid IPv4 address: {config['Proxy']['ServerHost']}") from exc

    if not 0 < config["Proxy"]["ServerPort"] < 65536:
        raise ValueError(f"Invalid port: {config['Proxy']['ServerPort']}")

    return config


def init_logger(config):
    """
    Initializes the logging system based on the configuration.

    :param config: Configuration settings
    :return: Logger object
    """
    logger = logging.getLogger()
    logger.setLevel(
        getattr(
            logging,
            config["Logging"].get("LogLevel", "INFO").upper(),
            logging.INFO,
        )
    )

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if config["Logging"].get("Enable", False):
        log_file = config["Logging"].get("LogFile", "modbus_proxy.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


class PersistentModbusClient:
    """
    A wrapper class for maintaining a persistent Modbus TCP connection.
    """
    def __init__(self, host, port, logger, retry_interval=5):
        self.host = host
        self.port = port
        self.logger = logger
        self.retry_interval = retry_interval
        self.client = None

    def connect(self):
        """
        Establish a connection to the Modbus server.
        Reconnect if the connection is lost.
        """
        while not self.client or not self.client.is_socket_open():
            try:
                self.client = ModbusTcpClient(self.host, self.port)
                if self.client.connect():
                    self.logger.info("Successfully connected to Modbus server.")
                else:
                    raise ConnectionError("Failed to connect to Modbus server.")
            except Exception as exc:
                self.logger.error("Connection error: %s. Retrying in %d seconds.", exc, self.retry_interval)
                time.sleep(self.retry_interval)

    def send_request(self, data):
        """
        Send a request to the Modbus server and return the response.

        :param data: Request data to be sent.
        :return: Response data received from the server.
        """
        if not self.client or not self.client.is_socket_open():
            self.logger.warning("Modbus connection lost. Reconnecting...")
            self.connect()

        try:
            self.client.socket.sendall(data)
            return self.client.socket.recv(1024)
        except Exception as exc:
            self.logger.error("Error during communication: %s", exc)
            self.connect()
            raise

    def close(self):
        """
        Close the Modbus connection.
        """
        if self.client:
            self.client.close()
            self.logger.info("Modbus connection closed.")


def handle_client(client_socket, client_address, request_queue, logger):
    """
    Handles a client connection.

    :param client_socket: Client socket
    :param client_address: Client's address
    :param request_queue: Request queue
    :param logger: Logger object
    """
    try:
        logger.info("New client connected: %s", client_address)
        while True:
            data = client_socket.recv(1024)
            if not data:  # Client closed the connection
                logger.info("Client disconnected: %s", client_address)
                break
            request_queue.put((data, client_socket))
    except (socket.error, OSError) as exc:
        logger.error("Error with client %s: %s", client_address, exc)
    finally:
        client_socket.close()  # Ensure the socket is closed
        logger.info("Socket for %s closed", client_address)


def process_requests(request_queue, persistent_client, logger):
    """
    Processes requests to the Modbus server using a persistent connection.

    :param request_queue: Request queue
    :param persistent_client: PersistentModbusClient instance
    :param logger: Logger object
    """
    while True:
        try:
            data, client_socket = request_queue.get()
            if client_socket.fileno() == -1:  # Check if socket is valid
                logger.error("Client socket is closed. Skipping request.")
                continue
            try:
                response = persistent_client.send_request(data)
                if client_socket.fileno() != -1:  # Double-check before sending
                    client_socket.sendall(response)
                else:
                    logger.warning("Client socket closed before sending response.")
            except Exception as exc:
                logger.error("Error processing request: %s", exc)
                client_socket.close()
        except (queue.Empty, OSError) as exc:
            logger.error("Error processing queue: %s", exc)


def start_server(config):
    """
    Starts the proxy server with persistent Modbus connection.

    :param config: Configuration settings
    """
    logger = init_logger(config)

    max_queue_size = max(10, min(1000, threading.active_count() * 10))
    request_queue = queue.Queue(maxsize=max_queue_size)

    cpu_count = os.cpu_count() or 4
    max_workers = max(4, cpu_count * 2)

    persistent_client = PersistentModbusClient(
        config["ModbusServer"]["ModbusServerHost"],
        int(config["ModbusServer"]["ModbusServerPort"]),
        logger
    )
    persistent_client.connect()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(
            (config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"])
        )
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
        except OSError as exc:
            logger.error("Server error: %s", exc)
        finally:
            logger.info("Closing persistent Modbus client.")
            persistent_client.close()
            logger.info("Closing server socket.")
            server_socket.close()


if __name__ == "__main__":
    try:
        configuration = load_config()
        start_server(configuration)
    except FileNotFoundError as exc:
        print(f"Configuration file not found: {exc}")
    except ValueError as exc:
        print(f"Invalid configuration: {exc}")
    except OSError as exc:
        print(f"OS error: {exc}")
    except KeyboardInterrupt:
        print("Server shutdown requested by user.")

