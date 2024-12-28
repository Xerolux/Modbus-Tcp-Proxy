import socket
import threading
import time
import yaml
from pymodbus.client.sync import ModbusTcpClient
import logging

# Load configuration
with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)

SERVER_HOST = config["Proxy"]["ServerHost"]
SERVER_PORT = int(config["Proxy"]["ServerPort"])
MODBUS_SERVER_HOST = config["ModbusServer"]["ModbusServerHost"]
MODBUS_SERVER_PORT = int(config["ModbusServer"]["ModbusServerPort"])
CONNECTION_TIMEOUT = int(config["ModbusServer"]["ConnectionTimeout"])
DELAY_AFTER_CONNECTION = float(config["ModbusServer"]["DelayAfterConnection"])

# Configure logging
if config.get("Logging", {}).get("Enable", False):
    log_file = config["Logging"].get("LogFile", "modbus_proxy.log")
    log_level = getattr(logging, config["Logging"].get("LogLevel", "INFO").upper(), logging.INFO)
    logging.basicConfig(filename=log_file, level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger()
else:
    logger = None

# Thread-safe request queue
request_queue = threading.Queue(maxsize=100)

# Handle each client connection
def handle_client(client_socket, client_address):
    try:
        if logger:
            logger.info(f"New client connected: {client_address}")
        else:
            print(f"New client connected: {client_address}")
        
        while True:
            data = client_socket.recv(1024)
            if not data:
                if logger:
                    logger.info(f"Client disconnected: {client_address}")
                else:
                    print(f"Client disconnected: {client_address}")
                break

            request_queue.put((data, client_socket))
    except Exception as e:
        if logger:
            logger.error(f"Error with client {client_address}: {e}")
        else:
            print(f"Error with client {client_address}: {e}")
    finally:
        client_socket.close()

# Process requests from the queue
def process_requests():
    while True:
        try:
            data, client_socket = request_queue.get()

            with ModbusTcpClient(MODBUS_SERVER_HOST, MODBUS_SERVER_PORT) as modbus_client:
                if not modbus_client.connect():
                    if logger:
                        logger.error(f"Failed to connect to Modbus server at {MODBUS_SERVER_HOST}:{MODBUS_SERVER_PORT}")
                    else:
                        print(f"Failed to connect to Modbus server at {MODBUS_SERVER_HOST}:{MODBUS_SERVER_PORT}")
                    continue

                if logger:
                    logger.info(f"Connected to Modbus server at {MODBUS_SERVER_HOST}:{MODBUS_SERVER_PORT}")
                else:
                    print(f"Connected to Modbus server at {MODBUS_SERVER_HOST}:{MODBUS_SERVER_PORT}")

                time.sleep(DELAY_AFTER_CONNECTION)

                modbus_client.socket.sendall(data)
                response = modbus_client.socket.recv(1024)
                client_socket.sendall(response)

        except Exception as e:
            if logger:
                logger.error(f"Error processing request: {e}")
            else:
                print(f"Error processing request: {e}")

# Start the proxy server
def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((SERVER_HOST, SERVER_PORT))
    server_socket.listen(5)

    if logger:
        logger.info(f"Proxy server listening on {SERVER_HOST}:{SERVER_PORT}")
    else:
        print(f"Proxy server listening on {SERVER_HOST}:{SERVER_PORT}")

    threading.Thread(target=process_requests, daemon=True).start()

    while True:
        try:
            client_socket, client_address = server_socket.accept()
            threading.Thread(target=handle_client, args=(client_socket, client_address), daemon=True).start()
        except KeyboardInterrupt:
            if logger:
                logger.info("Shutting down server...")
            else:
                print("Shutting down server...")
            break
        except Exception as e:
            if logger:
                logger.error(f"Error in server: {e}")
            else:
                print(f"Error in server: {e}")

    server_socket.close()

if __name__ == "__main__":
    start_server()
