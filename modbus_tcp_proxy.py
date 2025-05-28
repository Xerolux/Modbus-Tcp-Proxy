import argparse
import os
import queue
import threading
import time
import logging
import socket
import ipaddress
import signal
import random
import re # Added for hostname validation
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from contextlib import contextmanager
import yaml
from cerberus import Validator
from pymodbus.client import ModbusTcpClient
from ipaddress import ip_address, ip_network

# Constants
MODBUS_TCP_HEADER_LENGTH = 6
DEFAULT_SOCKET_TIMEOUT = 60.0 # Default timeout for client sockets
DEFAULT_SERVER_SOCKET_TIMEOUT = 1.0 # Default timeout for server accept
DEFAULT_RECV_BUFFER_SIZE = 1024 # Default buffer size for socket receive

# Data classes for configurations
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

# Validierungsfunktion für Netzwerkeinstellungen
def validate_network_settings(field, value, error):
    """Custom validator for network settings"""
    # Regex for basic hostname validation (allows domain components up to 63 chars, separated by dots)
    # Does not fully comply with RFC 1035 but is a common practical approach.
    hostname_regex = re.compile(r"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$")
    try:
        if field == "ServerHost" or field == "ModbusServerHost":
            try:
                ipaddress.ip_address(value) # Valid IP address
            except ValueError:
                # Not an IP, try validating as a hostname
                if not hostname_regex.match(value):
                    error(field, "Invalid hostname or IP address. Hostnames must be valid as per RFC-like standards (e.g., 'my.server-1.com').")
                # Optional: Check for length constraints if needed, e.g. total length <= 253
                # For simplicity, we rely on the regex for component length.
    except Exception as e: # Catch any unexpected error during validation
        error(field, f"Validation error: {str(e)}")

# Configuration validation
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
    
    # Environment variables override configuration values if present
    for section in config:
        for key in config[section]:
            env_var = f"MODBUS_PROXY_{section.upper()}_{key.upper()}"
            if env_var in os.environ:
                if isinstance(config[section][key], bool):
                    config[section][key] = os.environ[env_var].lower() in ('true', '1', 'yes')
                elif isinstance(config[section][key], int):
                    config[section][key] = int(os.environ[env_var])
                elif isinstance(config[section][key], float):
                    config[section][key] = float(os.environ[env_var])
                else:
                    config[section][key] = os.environ[env_var]

    return validator.normalized(config)

# Konfiguration laden
def load_config(config_path):
    """Load configuration from YAML file with environment variable support"""
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return validate_config(config)

# Initialize logger
def init_logger(config):
    """
    Initialize logger with appropriate configuration.
    Note: DEBUG level logging can be very verbose and may expose sensitive data 
    (like Modbus packet contents). Use with caution in production environments.
    """
    logger = logging.getLogger()
    # Remove all existing handlers to prevent duplicate logs if re-initialized
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close() # Ensure handlers are closed before removal

    logger.setLevel(config["Logging"].get("LogLevel", "INFO").upper())
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if config["Logging"].get("Enable", False):
        log_file = config["Logging"].get("LogFile", "modbus_proxy.log")
        try:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except (PermissionError, OSError) as e:
            # Fallback or clearer error if file logging is essential could be added here
            print(f"Warning: Could not set up file logging to '{log_file}': {str(e)}")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger

# Modbus-Client-Klasse
class PersistentModbusClient:
    """Enhanced Modbus client with better connection management"""
    def __init__(self, modbus_config, logger):
        self.config = modbus_config
        self.logger = logger
        self.client = None
        self._lock = threading.RLock()

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
                    # else: # This 'else' is redundant as client.connect() itself raises on failure
                    #     raise ConnectionError("Failed to connect to Modbus server.") # pymodbus typically raises its own error
                except (socket.error, OSError, ConnectionError, Exception) as exc: # Added generic Exception for robustness
                    attempts += 1
                    if attempts >= self.config.max_retries:
                        self.logger.critical(f"Max retries ({self.config.max_retries}) reached for connecting to Modbus server. Giving up. Error: {exc}")
                        raise # Re-raise the last exception
                    
                    backoff_time = min(self.config.max_backoff, (2 ** attempts) + random.uniform(0, 1))
                    self.logger.error(f"Connection error to Modbus server: {exc}. Attempt {attempts} of {self.config.max_retries}. "
                                      f"Retrying in {backoff_time:.2f}s")
                    time.sleep(backoff_time)
    
    @contextmanager
    def connection(self):
        """Context manager for ensuring connection is active"""
        try:
            if not self.client or not self.client.is_socket_open():
                self.connect() # Attempt to connect if not connected
            yield self.client
        except (socket.error, OSError, ConnectionError) as conn_exc: # Specific exceptions related to connection
            self.logger.error(f"Modbus connection error prior to/during operation: {conn_exc}")
            # Attempt to re-establish connection once if it fails within context
            try:
                self.connect()
                yield self.client # Yield again if reconnected
            except Exception as reconn_exc:
                self.logger.error(f"Failed to re-establish Modbus connection: {reconn_exc}")
                raise # Raise if reconnect also fails
        except Exception as exc: # Catch other unexpected errors
            self.logger.error(f"Unexpected error in Modbus connection context: {exc}")
            raise # Re-raise other exceptions

    def _read_exact(self, client_socket, length_to_read):
        """Helper function to read an exact number of bytes from a socket."""
        response_data = b""
        bytes_remaining = length_to_read
        client_socket.settimeout(self.config.timeout) # Ensure timeout is set for this operation
        
        while bytes_remaining > 0:
            try:
                chunk = client_socket.recv(min(bytes_remaining, DEFAULT_RECV_BUFFER_SIZE))
                if not chunk:
                    self.logger.warning("Modbus server closed connection prematurely while reading response.")
                    raise ConnectionAbortedError("Modbus server closed connection prematurely.")
                response_data += chunk
                bytes_remaining -= len(chunk)
            except socket.timeout:
                self.logger.warning(f"Socket recv timeout reached while waiting for {length_to_read} bytes. Received {len(response_data)} bytes so far.")
                raise # Re-raise timeout to be handled by caller
            except socket.error as sock_err:
                self.logger.error(f"Socket error while reading response: {sock_err}")
                raise
        return response_data

    def send_request(self, data):
        """Send request to Modbus server and read response robustly based on Modbus TCP header."""
        with self._lock:
            try:
                with self.connection() as client: # Ensures client is connected
                    if client.socket is None:
                        self.logger.error("Modbus client socket is not available.")
                        raise ConnectionError("Modbus client socket is not available.")

                    self.logger.debug(f"Sending request: {data.hex()}")
                    client.socket.sendall(data)
                    
                    # Read the Modbus TCP header (first 6 bytes)
                    header = self._read_exact(client.socket, MODBUS_TCP_HEADER_LENGTH)
                    
                    # Bytes 4 and 5 of the header contain the length of the PDU (Protocol Data Unit)
                    # This length is the number of bytes *following* the header.
                    pdu_length = (header[4] << 8) + header[5]
                    
                    # Read the rest of the PDU
                    pdu = self._read_exact(client.socket, pdu_length)
                    
                    response = header + pdu
                    self.logger.debug(f"Received response: {response.hex()} (Header: {header.hex()}, PDU: {pdu.hex()})")
                    return response
            except (socket.error, ConnectionError, ConnectionAbortedError, socket.timeout) as exc:
                self.logger.error(f"Communication error during Modbus request/response: {exc}")
                # Consider closing and reconnecting the client here or let the context manager handle it
                if self.client: # Attempt to close the client socket if it exists on error
                    try:
                        self.client.close()
                    except Exception as close_exc:
                        self.logger.warning(f"Error closing Modbus client after communication error: {close_exc}")
                raise # Re-raise the caught exception to be handled by the caller (process_requests)
            except Exception as exc: # Catch any other unexpected errors
                self.logger.error(f"Unexpected error in send_request: {exc}")
                if self.client:
                    try:
                        self.client.close()
                    except Exception as close_exc:
                        self.logger.warning(f"Error closing Modbus client after unexpected error: {close_exc}")
                raise


    def close(self):
        """Safely close connection"""
        with self._lock:
            if self.client:
                try:
                    self.client.close()
                    self.logger.info("Modbus connection closed.")
                except (socket.error, OSError) as exc: # More specific exceptions
                    self.logger.warning(f"Error closing Modbus connection: {exc}")
                finally:
                    self.client = None # Ensure client is None even if close fails

# Handle client connections
def handle_client(client_socket, client_address, request_queue, logger, stop_event, active_connections, semaphore):
    """Handle individual client connections with improved resource management"""
    connection_id = f"{client_address[0]}:{client_address[1]}"
    active_connections[connection_id] = client_socket
    try:
        logger.info(f"New client connected: {connection_id}")
        client_socket.settimeout(DEFAULT_SOCKET_TIMEOUT) # Use defined constant
        while not stop_event.is_set():
            try:
                data = client_socket.recv(DEFAULT_RECV_BUFFER_SIZE) # Use defined constant
                if not data:
                    logger.info(f"Client disconnected: {connection_id}")
                    break
                request_queue.put((data, client_socket, connection_id))
            except socket.timeout:
                if stop_event.is_set(): # Check stop_event after timeout
                    logger.debug(f"Client handler {connection_id} stopping due to stop_event after timeout.")
                    break
                continue # Continue if not stopping, just a regular timeout
            except (socket.error, OSError) as exc:
                logger.error(f"Socket error with client {connection_id}: {exc}")
                break
            except Exception as exc: # Catch any other unexpected errors
                logger.error(f"Unexpected error in handle_client for {connection_id}: {exc}")
                break
    finally:
        try:
            # Ensure socket is valid and not already closed before attempting to close
            if client_socket and client_socket.fileno() != -1:
                client_socket.close()
        except (socket.error, OSError) as sock_err: # Catch errors during close
            logger.warning(f"Error closing client socket for {connection_id}: {sock_err}")
        except Exception as exc: # Catch any other potential error during close
            logger.warning(f"Unexpected error closing client socket for {connection_id}: {exc}")
        
        if connection_id in active_connections:
            del active_connections[connection_id]
        
        semaphore.release() # Ensure semaphore is always released
        logger.info(f"Socket for {connection_id} closed and resources released.")

# Process requests
def process_requests(request_queue, persistent_client, logger, stop_event, active_connections):
    """Process requests from the queue with improved error handling"""
    while not stop_event.is_set():
        try:
            data, client_socket, connection_id = request_queue.get(timeout=1.0) # Use float for timeout

            # Check if client is still considered active and socket is valid
            if connection_id not in active_connections or client_socket.fileno() == -1:
                logger.warning(f"Client {connection_id} disconnected or socket invalid before processing request. Discarding.")
                continue
            
            try:
                response = persistent_client.send_request(data)
                # Double check client connection before sending response
                if connection_id in active_connections and client_socket.fileno() != -1:
                    client_socket.sendall(response)
                else:
                    logger.warning(f"Client {connection_id} disconnected before sending response.")
            except (socket.error, ConnectionError, ConnectionAbortedError, socket.timeout) as exc: # More specific
                logger.error(f"Communication error processing request for {connection_id}: {exc}. Client may be disconnected.")
                # Attempt to close the client socket on error
                try:
                    if client_socket.fileno() != -1:
                        client_socket.close()
                except (socket.error, OSError) as close_exc:
                    logger.warning(f"Error closing client socket for {connection_id} after processing error: {close_exc}")
                
                if connection_id in active_connections:
                    del active_connections[connection_id] # Remove from active connections
            except Exception as exc: # Catch other unexpected errors during send_request or sendall
                logger.error(f"Unexpected error processing request for {connection_id}: {exc}")
                if connection_id in active_connections: # Ensure cleanup if still present
                    try:
                        if client_socket.fileno() != -1: client_socket.close()
                    except Exception: pass # Best effort
                    del active_connections[connection_id]
        except queue.Empty:
            # This is expected if the queue is empty, continue waiting
            if stop_event.is_set():
                logger.debug("Request processor stopping due to stop_event after queue timeout.")
                break
            continue
        except Exception as exc: # Catch unexpected errors in the main loop of process_requests
            logger.critical(f"Critical unexpected error in request processor main loop: {exc}. Loop will continue.", exc_info=True)
            # Depending on severity, could add a small delay or specific recovery logic here
            if stop_event.is_set(): # Ensure loop termination if stop_event is set
                 logger.info("Request processor stopping due to stop_event after critical error.")
                 break

# Start server
def start_server(config):
    """Start the Modbus TCP proxy server with improved resource management"""
    logger = init_logger(config)
    logger.info("Starting Modbus TCP Proxy Server")
    
    stop_event = threading.Event()
    active_connections = {}
    cpu_count = os.cpu_count() or 4
    max_queue_size = max(10, min(1000, cpu_count * 25))
    request_queue = queue.Queue(maxsize=max_queue_size)
    max_workers = max(4, cpu_count * 2)
    connection_semaphore = threading.Semaphore(config["Proxy"]["MaxConnections"])
    
    # Support for CIDR notation in AllowedIPs
    allowed_networks = []
    if config["Proxy"]["AllowedIPs"]:
        for ip_or_network_str in config["Proxy"]["AllowedIPs"]:
            try:
                allowed_networks.append(ip_network(ip_or_network_str, strict=False)) # strict=False allows host addresses
            except ValueError:
                logger.warning(f"Invalid IP address or network in AllowedIPs: '{ip_or_network_str}'. Entry ignored.")
    
    modbus_config = ModbusConfig(
        host=config["ModbusServer"]["ModbusServerHost"],
        port=config["ModbusServer"]["ModbusServerPort"],
        timeout=config["ModbusServer"].get("ConnectionTimeout", 10),
        delay=config["ModbusServer"].get("DelayAfterConnection", 0.5),
        max_retries=config["ModbusServer"].get("MaxRetries", 5),
        max_backoff=config["ModbusServer"].get("MaxBackoff", 30.0)
    )
    
    persistent_client = PersistentModbusClient(modbus_config, logger)
    
    try:
        persistent_client.connect()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.submit(process_requests, request_queue, persistent_client, logger, stop_event, active_connections)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_socket.bind((config["Proxy"]["ServerHost"], config["Proxy"]["ServerPort"]))
                server_socket.listen(config["Proxy"].get("ListenBacklog", 5)) # Use config or default for backlog
                server_socket.settimeout(DEFAULT_SERVER_SOCKET_TIMEOUT) # Use defined constant
                logger.info(f"Proxy server listening on {config['Proxy']['ServerHost']}:{config['Proxy']['ServerPort']}")
                
                def shutdown_handler(signum, frame):
                    logger.info(f"Received shutdown signal {signal.Signals(signum).name}. Shutting down gracefully...")
                    stop_event.set()
                
                signal.signal(signal.SIGINT, shutdown_handler)
                signal.signal(signal.SIGTERM, shutdown_handler)
                
                while not stop_event.is_set():
                    try:
                        client_socket, client_address = server_socket.accept()
                        client_ip_str = client_address[0]
                        # Check allowed IPs with CIDR support
                        if allowed_networks: # Only check if allowed_networks is not empty
                            client_ip = ip_address(client_ip_str)
                            if not any(client_ip in net for net in allowed_networks):
                                logger.warning(f"Connection from {client_ip_str} (address: {client_ip}) not allowed. Closing connection.")
                                client_socket.close()
                                continue
                        
                        # Check maximum connections
                        if not connection_semaphore.acquire(blocking=False):
                            logger.warning(f"Maximum connections ({config['Proxy']['MaxConnections']}) reached. Connection from {client_ip_str} rejected.")
                            client_socket.close()
                            continue
                        
                        # Submit client handling to thread pool
                        executor.submit(handle_client, client_socket, client_address, request_queue, logger, stop_event, active_connections, connection_semaphore)
                    except socket.timeout:
                        # This is expected when server_socket.accept() times out
                        if stop_event.is_set(): # Check if shutdown was triggered during timeout
                            logger.debug("Server accept loop stopping due to stop_event after timeout.")
                            break
                        continue 
                    except OSError as os_err: # Catch errors like "Too many open files"
                        logger.error(f"OSError in server accept loop: {os_err}. May indicate system resource limits.")
                        if stop_event.is_set(): break # Ensure loop termination
                        time.sleep(0.1) # Brief pause before retrying accept
                    except Exception as e: # Catch any other unexpected errors during accept or setup
                        logger.error(f"Unexpected error in server accept loop: {e}", exc_info=True)
                        if stop_event.is_set(): break
                        # Consider if a short delay is needed here too
    finally:
        logger.info("Server shutdown sequence initiated...")
        if stop_event: # Ensure stop_event is set if not already
            stop_event.set()

        # Close all active client connections
        logger.info(f"Closing {len(active_connections)} active client connections...")
        for conn_id, sock in list(active_connections.items()): # Use list to avoid issues if dict changes
            try:
                if sock and sock.fileno() != -1:
                    sock.shutdown(socket.SHUT_RDWR) # Gracefully shutdown
                    sock.close()
                logger.debug(f"Closed client connection {conn_id}")
            except (socket.error, OSError) as e:
                logger.warning(f"Error closing client socket {conn_id}: {e}")
            if conn_id in active_connections: # remove safely
                 del active_connections[conn_id]
        
        # Close the Modbus client connection
        if persistent_client:
            persistent_client.close()
        
        # Server socket is closed by the 'with' statement for server_socket
        logger.info("Modbus TCP Proxy Server shut down complete.")

# Main program
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Modbus TCP Proxy Server")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to configuration file")
    args = parser.parse_args()
    
    config = load_config(args.config)
    start_server(config)
