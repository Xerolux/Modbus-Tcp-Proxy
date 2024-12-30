#!/usr/bin/env python3
import socket
import threading
import time
import yaml
import queue
import logging
import ipaddress
from pymodbus.client import ModbusTcpClient
from concurrent.futures import ThreadPoolExecutor
import os

# Load and validate configuration
def load_config():
    with open("config.yaml", "r") as file:
        config = yaml.safe_load(file)

    # Validate IP and port
    try:
        ipaddress.IPv4Address(config["Proxy"]["ServerHost"])
    except ipaddress.AddressValueError:
        raise ValueError(f"Invalid IPv4 address for SERVER_HOST: {config['Proxy']['ServerHost']}")
    if not (0 < config["Proxy"]["ServerPort"] < 65536):
        raise ValueError(f"Invalid port: {config['Proxy']['ServerPort']}")
    return config

# Initialize logging
def init_logger(config):
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, config["Logging"].get("LogLevel", "INFO").upper(), logging.INFO))

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # File handler
    if config["Logging"].get("Enable", False):
        log_file = config["Logging"].get("LogFile", "modbus_proxy.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# Handle client connection
def handle_client(client_socket, client_address, request_queue, logger):
    try:
        logger.info(f"New client connected: {client_address}")
        while True:
            data = client_socket.recv(1024)
            if not data:
                logger.info(f"Client disconnected: {client_address}")
                break
            request_queue.put((data, client_socket))
    except Exception as e:
        logger.error(f"Error with client {client_address}: {e}")
    finally:
        client_socket.close()

# Process requests to the Modbus server
def process_requests(request_queue, config, logger):
    while True:
        try:
            data, client_socket = request_queue.get()
            retry_attempts = 3
            connected = False

            for attempt in range(retry_attempts):
                try:
                    with ModbusTcpClient(config["ModbusServer"]["ModbusServerHost"], 
                                         port=int(config["ModbusServer"]["ModbusServerPort"])) as modbus_client:
                        if not modbus_client.connect():
                            raise ConnectionError(f"Attempt {attempt + 1}/{retry_attempts}: Connection failed")
                        connected = True
                        logger.info(f"Connected to Modbus server")

                        time.sleep(config["ModbusServer"]["DelayAfterConnection"])

                        modbus_client.socket.sendall(data)
                        response = modbus_client.socket.recv(1024)
                        client_socket.sendall(response)
                        break
                except Exception as e:
                    logger.error(f"Retry {attempt + 1} failed: {e}")
                    time.sleep(1)

            if not connected:
                logger.error("Failed to connect to Modbus server after retries")
                client_socket.close()
        except Exception as e:
            logger.error(f"Error processing request: {e}")

# Start server with thread pool
def start_server(config):
    logger = init_logger(config)

    # Dynamically adjust queue size based on system capacity
    max_queue_size = max(10, min(1000, threading.active_count() * 10))
    request_queue = queue.Queue(maxsize=max_queue_size)

    # Adjust thread pool size based on CPU cores and system load
    cpu_count = os.cpu_count() or 4  # Fallback to 4 if unable to detect
    max_workers = max(4, cpu_count * 2)  # Ensure at least 4 workers

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"]))
        server_socket.listen(5)
        logger.info(f"Proxy server listening on {config['Proxy']['ServerHost']}:{config['Proxy']['ServerPort']}")

        executor.submit(process_requests, request_queue, config, logger)

        try:
            while True:
                client_socket, client_address = server_socket.accept()
                executor.submit(handle_client, client_socket, client_address, request_queue, logger)
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            server_socket.close()

if __name__ == "__main__":
    try:
        config = load_config()
        start_server(config)
    except Exception as e:
        print(f"Startup error: {e}")
