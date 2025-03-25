import argparse
import os
import queue
import threading
import time
import logging
import socket
import ipaddress
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import yaml
from cerberus import Validator
from pymodbus.client import ModbusTcpClient

@dataclass
class ModbusConfig:
    host: str
    port: int
    timeout: int
    delay: float

def validate_config(config):
    schema = {
        'Proxy': {
            'type': 'dict',
            'schema': {
                'ServerHost': {'type': 'string', 'required': True},
                'ServerPort': {'type': 'integer', 'min': 1, 'max': 65535, 'required': True}
            }
        },
        'ModbusServer': {
            'type': 'dict',
            'schema': {
                'ModbusServerHost': {'type': 'string', 'required': True},
                'ModbusServerPort': {'type': 'integer', 'min': 1, 'max': 65535, 'required': True},
                'ConnectionTimeout': {'type': 'integer', 'min': 1, 'default': 10},
                'DelayAfterConnection': {'type': 'float', 'min': 0.0, 'default': 0.5}
            }
        },
        'Logging': {
            'type': 'dict',
            'schema': {
                'Enable': {'type': 'boolean', 'default': False},
                'LogFile': {'type': 'string', 'required': False},
                'LogLevel': {
                    'type': 'string',
                    'allowed': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                    'default': 'INFO'
                }
            }
        }
    }

    validator = Validator(schema)
    if not validator.validate(config):
        raise ValueError(f"Configuration validation failed: {validator.errors}")
    return validator.normalized(config)

def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return validate_config(config)

def init_logger(config):
    logger = logging.getLogger()
    logger.setLevel(config["Logging"].get("LogLevel", "INFO").upper())
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if config["Logging"].get("Enable", False):
        file_handler = logging.FileHandler(config["Logging"].get("LogFile", "modbus_proxy.log"))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

class PersistentModbusClient:
    def __init__(self, modbus_config, logger):
        self.config = modbus_config
        self.logger = logger
        self.client = None
        self.retries = 5

    def connect(self):
        attempts = 0
        while not self.client or not self.client.is_socket_open():
            try:
                self.client = ModbusTcpClient(
                    host=self.config.host,
                    port=self.config.port,
                    timeout=self.config.timeout
                )
                if self.client.connect():
                    self.logger.info("Successfully connected to Modbus server.")
                    time.sleep(self.config.delay)
                    return
                else:
                    raise ConnectionError("Failed to connect to Modbus server.")
            except (socket.error, OSError) as exc:
                attempts += 1
                self.logger.error("Connection error: %s. Attempt %d of %d.", exc, attempts, self.retries)
                if attempts >= self.retries:
                    self.logger.critical("Max retries reached. Giving up.")
                    raise
                time.sleep(0.1)

    def send_request(self, data):
        if not self.client or not self.client.is_socket_open():
            self.connect()

        try:
            self.logger.debug("Sending request: %s", data.hex())
            self.client.socket.sendall(data)

            # Read response in a loop to handle large payloads
            response = b""
            self.client.socket.settimeout(self.config.timeout)
            while True:
                try:
                    chunk = self.client.socket.recv(1024)
                    if not chunk:
                        break
                    response += chunk
                    if len(chunk) < 1024:
                        break  # Likely end of message
                except socket.timeout:
                    self.logger.warning("Socket recv timeout reached.")
                    break

            self.logger.debug("Received response: %s", response.hex())
            return response

        except socket.error as exc:
            self.logger.error("Communication error: %s", exc)
            self.connect()
            raise

    def close(self):
        if self.client:
            self.client.close()
            self.logger.info("Modbus connection closed.")

def handle_client(client_socket, client_address, request_queue, logger):
    try:
        logger.info("New client connected: %s", client_address)
        client_socket.settimeout(60)
        while True:
            try:
                data = client_socket.recv(1024)
                if not data:
                    logger.info("Client disconnected: %s", client_address)
                    break
                request_queue.put((data, client_socket))
            except socket.timeout:
                logger.warning("Client %s timeout, disconnecting.", client_address)
                break
    except (socket.error, OSError) as exc:
        logger.error("Error with client %s: %s", client_address, exc)
    finally:
        client_socket.close()
        logger.info("Socket for %s closed", client_address)

def process_requests(request_queue, persistent_client, logger, stop_event):
    while not stop_event.is_set():
        try:
            data, client_socket = request_queue.get(timeout=1)
            if client_socket.fileno() == -1:
                logger.error("Client socket is closed. Skipping request.")
                continue
            try:
                response = persistent_client.send_request(data)
                if client_socket.fileno() != -1:
                    client_socket.sendall(response)
                else:
                    logger.warning("Client socket closed before sending response.")
            except socket.error as exc:
                logger.error("Error processing request: %s", exc)
                client_socket.close()
        except queue.Empty:
            continue

def start_server(config):
    logger = init_logger(config)

    max_queue_size = max(10, min(1000, threading.active_count() * 10))
    request_queue = queue.Queue(maxsize=max_queue_size)
    stop_event = threading.Event()

    cpu_count = os.cpu_count() or 4
    max_workers = max(4, cpu_count * 2)

    modbus_config = ModbusConfig(
        host=config["ModbusServer"]["ModbusServerHost"],
        port=int(config["ModbusServer"]["ModbusServerPort"]),
        timeout=config["ModbusServer"].get("ConnectionTimeout", 10),
        delay=config["ModbusServer"].get("DelayAfterConnection", 0.5),
    )

    persistent_client = PersistentModbusClient(modbus_config, logger)
    persistent_client.connect()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"]))
        server_socket.listen(5)
        logger.info("Proxy server listening on %s:%d", config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"])

        def shutdown_handler(signum, frame):
            logger.info("Received shutdown signal. Closing resources...")
            stop_event.set()
            server_socket.close()
            persistent_client.close()
            exit(0)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        executor.submit(process_requests, request_queue, persistent_client, logger, stop_event)

        try:
            while not stop_event.is_set():
                try:
                    client_socket, client_address = server_socket.accept()
                    executor.submit(handle_client, client_socket, client_address, request_queue, logger)
                except socket.error:
                    if stop_event.is_set():
                        break
        except OSError as exc:
            logger.error("Server error: %s", exc)
        finally:
            logger.info("Closing persistent Modbus client.")
            persistent_client.close()
            logger.info("Closing server socket.")
            server_socket.close()

def parse_arguments():
    parser = argparse.ArgumentParser(description="Modbus TCP Proxy Server")
    parser.add_argument("--config", required=True, help="Path to the configuration file (YAML format)")
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
