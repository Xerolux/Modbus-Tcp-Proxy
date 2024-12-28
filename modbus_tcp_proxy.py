import socket
import threading
import time
import yaml
from pymodbus.client.sync import ModbusTcpClient

# Load configuration
with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)

SERVER_HOST = config["Proxy"]["ServerHost"]
SERVER_PORT = int(config["Proxy"]["ServerPort"])
MODBUS_SERVER_HOST = config["ModbusServer"]["ModbusServerHost"]
MODBUS_SERVER_PORT = int(config["ModbusServer"]["ModbusServerPort"])
CONNECTION_TIMEOUT = int(config["ModbusServer"]["ConnectionTimeout"])
DELAY_AFTER_CONNECTION = float(config["ModbusServer"]["DelayAfterConnection"])

# Thread-safe request queue
request_queue = threading.Queue()

# Handle each client connection
def handle_client(client_socket, client_address):
    try:
        print(f"New client connected: {client_address}")
        while True:
            # Receive data from client
            data = client_socket.recv(1024)
            if not data:
                print(f"Client disconnected: {client_address}")
                break

            # Enqueue the request
            request_queue.put((data, client_socket))
    except Exception as e:
        print(f"Error with client {client_address}: {e}")
    finally:
        client_socket.close()

# Process requests from the queue
def process_requests():
    while True:
        try:
            # Get the next request
            data, client_socket = request_queue.get()

            # Connect to the Modbus server
            with ModbusTcpClient(MODBUS_SERVER_HOST, MODBUS_SERVER_PORT) as modbus_client:
                modbus_client.connect()
                print(f"Connected to Modbus server at {MODBUS_SERVER_HOST}:{MODBUS_SERVER_PORT}")

                # Delay after connection if configured
                time.sleep(DELAY_AFTER_CONNECTION)

                # Send the data to the Modbus server
                modbus_client.socket.sendall(data)

                # Receive the response
                response = modbus_client.socket.recv(1024)

                # Send the response back to the client
                client_socket.sendall(response)

        except Exception as e:
            print(f"Error processing request: {e}")

# Start the proxy server
def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((SERVER_HOST, SERVER_PORT))
    server_socket.listen(5)
    print(f"Proxy server listening on {SERVER_HOST}:{SERVER_PORT}")

    # Start the request processing thread
    threading.Thread(target=process_requests, daemon=True).start()

    while True:
        try:
            client_socket, client_address = server_socket.accept()
            threading.Thread(target=handle_client, args=(client_socket, client_address), daemon=True).start()
        except KeyboardInterrupt:
            print("Shutting down server...")
            break
        except Exception as e:
            print(f"Error in server: {e}")

    server_socket.close()

if __name__ == "__main__":
    start_server()
