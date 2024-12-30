#!/usr/bin/env python3
"""
Modbus TCP Proxy Server

This module implements a proxy server for Modbus TCP requests.
It includes functions for loading the configuration, processing requests, and starting the server.
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
            if not data:
                logger.info("Client disconnected: %s", client_address)
                break
            request_queue.put((data, client_socket))
    except (socket.error, OSError) as exc:
        logger.error("Error with client %s: %s", client_address, exc)
    finally:
        client_socket.close()


def process_requests(request_queue, config, logger):
    """
    Processes requests to the Modbus server.

    :param request_queue: Request queue
    :param config: Configuration settings
    :param logger: Logger object
    """
    while True:
        try:
            data, client_socket = request_queue.get()
            retry_attempts = 3

            for attempt in range(retry_attempts):
                try:
                    with ModbusTcpClient(
                        config["ModbusServer"]["ModbusServerHost"],
                        port=int(config["ModbusServer"]["ModbusServerPort"]),
                    ) as modbus_client:
                        if not modbus_client.connect():
                            raise ConnectionError(
                                f"Attempt {attempt + 1}/{retry_attempts}: Connection failed"
                            )

                        logger.info("Connected to Modbus server")
                        time.sleep(
                            config["ModbusServer"].get("DelayAfterConnection", 0)
                        )

                        modbus_client.socket.sendall(data)
                        response = modbus_client.socket.recv(1024)
                        client_socket.sendall(response)
                        break
                except (ConnectionError, TimeoutError) as exc:
                    logger.error("Retry %d failed: %s", attempt + 1, exc)
                    time.sleep(1)
            else:
                logger.error("Failed to connect to Modbus server after retries")
                client_socket.close()
        except (queue.Empty, OSError) as exc:
            logger.error("Error processing request: %s", exc)


def start_server(config):
    """
    Starts the proxy server.

    :param config: Configuration settings
    """
    logger = init_logger(config)

    max_queue_size = max(10, min(1000, threading.active_count() * 10))
    request_queue = queue.Queue(maxsize=max_queue_size)

    cpu_count = os.cpu_count() or 4
    max_workers = max(4, cpu_count * 2)

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

        executor.submit(process_requests, request_queue, config, logger)

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
            server_socket.close()


if __name__ == "__main__":
    try:
        configuration = load_config()
        start_server(configuration)
    except Exception as exc:
        print(f"Startup error: {exc}")
