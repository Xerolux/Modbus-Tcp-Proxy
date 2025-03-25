import argparse
import os
import queue
import threading
import time
import logging
import socket
import ipaddress
import signal
import math
import sys
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from contextlib import contextmanager
import yaml
from cerberus import Validator
from pymodbus.client import ModbusTcpClient

@dataclass
class ModbusConfig:
    host: str
    port: int
    timeout: int
    delay: float
    max_retries: int = 5
    max_backoff: float = 30.0

@dataclass
class ProxyConfig:
    host: str
    port: int
    allowed_ips: list = None
    max_connections: int = 100

def validate_network_settings(field, value, error):
    """Custom validator for network settings"""
    try:
        if field == "ServerHost" or field == "ModbusServerHost":
            # Validate if it's a proper hostname or IP
            try:
                ipaddress.ip_address(value)
            except ValueError:
                # Not an IP, check if it's a valid hostname
                if not all(c.isalnum() or c in ".-" for c in value):
                    error(field, "Invalid hostname or IP address")
    except Exception as e:
        error(field, f"Validation error: {str(e)}")

def validate_config(config):
    """Validate and normalize configuration with enhanced validation"""
    schema = {
        'Proxy': {
            'type': 'dict',
            'schema': {
                'ServerHost': {
                    'type': 'string',
                    'required': True,
                    'check_with': validate_network_settings
                },
                'ServerPort': {
                    'type': 'integer',
                    'min': 1,
                    'max': 65535,
                    'required': True
                },
                'AllowedIPs': {
                    'type': 'list',
                    'schema': {'type': 'string'},
                    'default': []
                },
                'MaxConnections': {
                    'type': 'integer',
                    'min': 1,
                    'max': 10000,
                    'default': 100
                }
            }
        },
        'ModbusServer': {
            'type': 'dict',
            'schema': {
                'ModbusServerHost': {
                    'type': 'string',
                    'required': True,
                    'check_with': validate_network_settings
                },
                'ModbusServerPort': {
                    'type': 'integer',
                    'min': 1,
                    'max': 65535,
                    'required': True
                },
                'ConnectionTimeout': {
                    'type': 'integer',
                    'min': 1,
                    'default': 10
                },
                'DelayAfterConnection': {
                    'type': 'float',
                    'min': 0.0,
                    'default': 0.5
                },
                'MaxRetries': {
                    'type': 'integer',
                    'min': 1,
                    'default': 5
                },
                'MaxBackoff': {
                    'type': 'float',
                    'min': 1.0,
                    'default': 30.0
                }
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
    
    # Apply environment variable overrides
    for section in config:
        for key in config[section]:
            env_var = f"MODBUS_PROXY_{section.upper()}_{key.upper()}"
            if env_var in os.environ:
                # Convert types based on schema
                if isinstance(config[section][key], bool):
                    config[section][key] = os.environ[env_var].lower() in ('true', '1', 'yes')
                elif isinstance(config[section][key], int):
                    config[section][key] = int(os.environ[env_var])
                elif isinstance(config[section][key], float):
                    config[section][key] = float(os.environ[env_var])
                else:
                    config[section][key] = os.environ[env_var]

    return validator.normalized(config)

def load_config(config_path):
    """Load configuration from YAML file with environment variable support"""
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return validate_config(config)

def init_logger(config):
    """Initialize logger with appropriate configuration"""
    logger = logging.getLogger()
    
    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    logger.setLevel(config["Logging"].get("LogLevel", "INFO").upper())
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if config["Logging"].get("Enable", False):
        try:
            file_handler = logging.FileHandler(config["Logging"].get("LogFile", "modbus_proxy.log"))
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except (PermissionError, OSError) as e:
            # Fall back to console logging if file logging fails
            print(f"Warning: Could not set up file logging: {str(e)}")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

class PersistentModbusClient:
    """Enhanced Modbus client with better connection management"""
    def __init__(self, modbus_config, logger):
        self.config = modbus_config
        self.logger = logger
        self.client = None
        self._lock = threading.RLock()  # Reentrant lock for thread safety

    def connect(self):
        """Connect to Modbus server with exponential backoff retry strategy"""
        with self._lock:
            attempts = 0
            while not self.client or not self.client.is_socket_open():
                try:
                    if self.client:
                        self.client.close()
                    
                    self.logger.info(f"Connecting to Modbus server at {self.config.host}:{self.config.port}")
                    self.client = ModbusTcpClient(
                        host=self.config.host,
                        port=self.config.port,
                        timeout=self.config.timeout
                    )
                    
                    if self.client.connect():
                        self.logger.info("Successfully connected to Modbus server.")
                        time.sleep(self.config.delay)
                        return True
                    else:
                        raise ConnectionError("Failed to connect to Modbus server.")
                        
                except (socket.error, OSError, ConnectionError) as exc:
                    attempts += 1
                    
                    if attempts >= self.config.max_retries:
                        self.logger.critical(f"Max retries ({self.config.max_retries}) reached. Giving up.")
                        raise
                    
                    # Calculate backoff time with exponential strategy
                    backoff = min(self.config.max_backoff, (2 ** attempts) + (random.uniform(0, 1)))
                    self.logger.error(f"Connection error: {exc}. Attempt {attempts} of {self.config.max_retries}. "
                                      f"Retrying in {backoff:.2f}s")
                    time.sleep(backoff)
    
    @contextmanager
    def connection(self):
        """Context manager for ensuring connection is active"""
        try:
            if not self.client or not self.client.is_socket_open():
                self.connect()
            yield self.client
        except Exception as exc:
            self.logger.error(f"Connection error: {exc}")
            self.connect()  # Try to reconnect for next time
            raise
    
    def send_request(self, data):
        """Send request to Modbus server with improved error handling"""
        with self._lock:  # Ensure thread safety for the connection
            try:
                with self.connection() as client:
                    self.logger.debug(f"Sending request: {data.hex()}")
                    client.socket.sendall(data)

                    # Read response in a loop to handle large payloads
                    response = b""
                    client.socket.settimeout(self.config.timeout)
                    
                    while True:
                        try:
                            chunk = client.socket.recv(1024)
                            if not chunk:
                                break
                            response += chunk
                            if len(chunk) < 1024:
                                break  # Likely end of message
                        except socket.timeout:
                            self.logger.warning("Socket recv timeout reached.")
                            break

                    self.logger.debug(f"Received response: {response.hex()}")
                    return response

            except (socket.error, ConnectionError) as exc:
                self.logger.error(f"Communication error during request: {exc}")
                raise

    def close(self):
        """Safely close connection"""
        with self._lock:
            if self.client:
                try:
                    self.client.close()
                    self.logger.info("Modbus connection closed.")
                except Exception as exc:
                    self.logger.warning(f"Error closing Modbus connection: {exc}")
                finally:
                    self.client = None

def handle_client(client_socket, client_address, request_queue, logger, stop_event, active_connections):
    """Handle individual client connections with improved resource management"""
    connection_id = f"{client_address[0]}:{client_address[1]}"
    
    # Register connection
    active_connections[connection_id] = client_socket
    
    try:
        logger.info(f"New client connected: {connection_id}")
        client_socket.settimeout(60)
        
        while not stop_event.is_set():
            try:
                data = client_socket.recv(1024)
                if not data:
                    logger.info(f"Client disconnected: {connection_id}")
                    break
                
                request_queue.put((data, client_socket, connection_id))
            except socket.timeout:
                # Check if we should keep this connection
                if stop_event.is_set():
                    break
                continue
            except (socket.error, OSError) as exc:
                logger.error(f"Error with client {connection_id}: {exc}")
                break
            
    finally:
        try:
            client_socket.close()
        except Exception:
            pass
            
        if connection_id in active_connections:
            del active_connections[connection_id]
                
        logger.info(f"Socket for {connection_id} closed")

def process_requests(request_queue, persistent_client, logger, stop_event, active_connections):
    """Process requests from the queue with improved error handling"""
    while not stop_event.is_set():
        try:
            data, client_socket, connection_id = request_queue.get(timeout=1)
            
            # Check if client is still connected
            if connection_id not in active_connections or client_socket.fileno() == -1:
                logger.warning(f"Client {connection_id} disconnected before processing request")
                continue
                
            try:
                response = persistent_client.send_request(data)
                
                # Check again if client is still connected
                if connection_id in active_connections and client_socket.fileno() != -1:
                    client_socket.sendall(response)
                else:
                    logger.warning(f"Client {connection_id} disconnected before sending response")
            except (socket.error, ConnectionError) as exc:
                logger.error(f"Error processing request from {connection_id}: {exc}")
                
                # Close the connection on error
                try:
                    if client_socket.fileno() != -1:
                        client_socket.close()
                except Exception:
                    pass
                
                if connection_id in active_connections:
                    del active_connections[connection_id]
                
        except queue.Empty:
            continue
        except Exception as exc:
            logger.error(f"Unexpected error in request processor: {exc}")

def start_server(config):
    """Start the Modbus TCP proxy server with improved resource management"""
    logger = init_logger(config)
    logger.info("Starting Modbus TCP Proxy Server")
    
    # Create shared resources
    stop_event = threading.Event()
    active_connections = {}
    
    # Determine queue size based on system resources
    cpu_count = os.cpu_count() or 4
    max_queue_size = max(10, min(1000, cpu_count * 25))
    request_queue = queue.Queue(maxsize=max_queue_size)
    
    # Determine thread pool size
    max_workers = max(4, cpu_count * 2)
    
    # Create Modbus client configuration
    modbus_config = ModbusConfig(
        host=config["ModbusServer"]["ModbusServerHost"],
        port=config["ModbusServer"]["ModbusServerPort"],
        timeout=config["ModbusServer"].get("ConnectionTimeout", 10),
        delay=config["ModbusServer"].get("DelayAfterConnection", 0.5),
        max_retries=config["ModbusServer"].get("MaxRetries", 5),
        max_backoff=config["ModbusServer"].get("MaxBackoff", 30.0)
    )
    
    # Create persistent Modbus client
    persistent_client = PersistentModbusClient(modbus_config, logger)
    
    try:
        # Initial connection to Modbus server
        persistent_client.connect()
        
        # Create thread pool
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Start request processor
            executor.submit(process_requests, request_queue, persistent_client, logger, stop_event, active_connections)
            
            # Create server socket with context manager for cleanup
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
                # Set socket options for address reuse
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
                # Bind and listen
                server_socket.bind((config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"]))
                server_socket.listen(5)
                server_socket.settimeout(1)  # Allow checking stop_event periodically
                
                logger.info(f"Proxy server listening on {config['Proxy']['ServerHost']}:{config['Proxy']['ServerPort']}")
                
                # Set up signal handlers
                def shutdown_handler(signum, frame):
                    logger.info(f"Received shutdown signal {signum}. Shutting down gracefully...")
                    stop_event.set()
                
                signal.signal(signal.SIGINT, shutdown_handler)
                signal.signal(signal.SIGTERM, shutdown_handler)
                
                # Accept connections until stop event
                while not stop_event.is_set():
                    try:
                        client
