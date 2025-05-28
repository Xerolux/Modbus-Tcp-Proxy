import unittest
from unittest.mock import patch, MagicMock, mock_open, call
import os
import yaml
import ipaddress
import logging

# Assuming modbus_tcp_proxy.py is in the parent directory or PYTHONPATH is set up
# For testing, it's often easier to adjust sys.path or ensure the module is installable
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modbus_tcp_proxy import (
    load_config,
    validate_config,
    validate_network_settings,
    PersistentModbusClient,
    ModbusConfig,
    ProxyConfig,
    init_logger,
    handle_client,
    process_requests,
    start_server, # For some integration-like tests
    MODBUS_TCP_HEADER_LENGTH,
    DEFAULT_RECV_BUFFER_SIZE
)

# Disable logging for tests unless specifically testing logging
logging.disable(logging.CRITICAL)

class TestConfigValidation(unittest.TestCase):
    def test_validate_network_settings_valid_ip(self):
        error_mock = MagicMock()
        validate_network_settings("ServerHost", "127.0.0.1", error_mock)
        error_mock.assert_not_called()

    def test_validate_network_settings_valid_hostname(self):
        error_mock = MagicMock()
        validate_network_settings("ServerHost", "my.valid-host.com", error_mock)
        error_mock.assert_not_called()

    def test_validate_network_settings_invalid_hostname(self):
        error_mock = MagicMock()
        validate_network_settings("ServerHost", "invalid_host!", error_mock)
        error_mock.assert_called_once_with("ServerHost", "Invalid hostname or IP address. Hostnames must be valid as per RFC-like standards (e.g., 'my.server-1.com').")

    def test_validate_network_settings_invalid_ip_format(self):
        error_mock = MagicMock()
        # This will be caught by ipaddress.ip_address in the main validator,
        # but the custom validator also has a pattern for hostnames.
        # Test what the custom validator would do if it were solely responsible for hostnames.
        validate_network_settings("ServerHost", "300.300.300.300", error_mock)
        error_mock.assert_called_once_with("ServerHost", "Invalid hostname or IP address. Hostnames must be valid as per RFC-like standards (e.g., 'my.server-1.com').")


    def get_base_valid_config(self):
        return {
            'Proxy': {
                'ServerHost': '0.0.0.0',
                'ServerPort': 5020,
                'AllowedIPs': ['192.168.1.0/24', '10.0.0.1'],
                'MaxConnections': 50
            },
            'ModbusServer': {
                'ModbusServerHost': '192.168.1.100',
                'ModbusServerPort': 502,
                'ConnectionTimeout': 5,
                'DelayAfterConnection': 0.1,
                'MaxRetries': 3,
                'MaxBackoff': 10.0
            },
            'Logging': {
                'Enable': False,
                'LogFile': 'proxy.log',
                'LogLevel': 'INFO'
            }
        }

    def test_validate_config_valid(self):
        config = self.get_base_valid_config()
        try:
            validated_config = validate_config(config)
            self.assertIsNotNone(validated_config)
            # Check a few normalized values
            self.assertEqual(validated_config['Proxy']['ServerHost'], '0.0.0.0')
            self.assertEqual(validated_config['ModbusServer']['ConnectionTimeout'], 5)
        except ValueError as e:
            self.fail(f"Validation failed for a valid config: {e}")

    def test_validate_config_missing_required_field(self):
        config = self.get_base_valid_config()
        del config['Proxy']['ServerHost']
        with self.assertRaisesRegex(ValueError, "Configuration validation failed: {'Proxy': [{'ServerHost': \['required field']}]}"):
            validate_config(config)

    def test_validate_config_invalid_port(self):
        config = self.get_base_valid_config()
        config['Proxy']['ServerPort'] = 70000 # Invalid port
        with self.assertRaisesRegex(ValueError, "Configuration validation failed: {'Proxy': [{'ServerPort': \['max value is 65535']}]}"):
            validate_config(config)

    def test_validate_config_invalid_ip_in_allowed_ips(self):
        # Note: The current validate_config doesn't deeply validate IP formats in AllowedIPs list using cerberus.
        # This is handled later in start_server. We test the schema validation here.
        config = self.get_base_valid_config()
        config['Proxy']['AllowedIPs'] = "not_a_list"
        with self.assertRaisesRegex(ValueError, "Configuration validation failed: {'Proxy': [{'AllowedIPs': \['must be of list type']}]}"):
            validate_config(config)

    @patch.dict(os.environ, {
        "MODBUS_PROXY_PROXY_SERVERPORT": "5555",
        "MODBUS_PROXY_MODBUSSERVER_CONNECTIONTIMEOUT": "7",
        "MODBUS_PROXY_LOGGING_ENABLE": "true"
    })
    def test_validate_config_env_override(self):
        config_data = self.get_base_valid_config()
        # Cerberus validator needs to be called for normalization and env var application
        validated_config = validate_config(config_data)

        self.assertEqual(validated_config['Proxy']['ServerPort'], 5555)
        self.assertEqual(validated_config['ModbusServer']['ConnectionTimeout'], 7)
        self.assertTrue(validated_config['Logging']['Enable'])

    @patch('builtins.open', new_callable=mock_open, read_data="---\nProxy:\n  ServerHost: 'localhost'\n  ServerPort: 5022\nModbusServer:\n  ModbusServerHost: 'modbus_server'\n  ModbusServerPort: 502\n")
    def test_load_config_valid_path(self, mock_file):
        with patch('modbus_tcp_proxy.validate_config') as mock_validate:
            mock_validate.return_value = {"Proxy": {"ServerPort": 5022}} # Simplified
            cfg = load_config("dummy_path.yaml")
            mock_file.assert_called_once_with("dummy_path.yaml", "r", encoding="utf-8")
            self.assertIn("Proxy", cfg)
            self.assertEqual(cfg["Proxy"]["ServerPort"], 5022)
            mock_validate.assert_called_once()

class TestPersistentModbusClient(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.modbus_config = ModbusConfig(
            host='127.0.0.1',
            port=502,
            timeout=3,
            delay=0.01,
            max_retries=3,
            max_backoff=1.0
        )

    @patch('modbus_tcp_proxy.ModbusTcpClient')
    def test_connect_successful(self, MockModbusClient):
        mock_client_instance = MockModbusClient.return_value
        mock_client_instance.connect.return_value = True
        mock_client_instance.is_socket_open.return_value = True

        persistent_client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        result = persistent_client.connect()

        self.assertTrue(result)
        mock_client_instance.connect.assert_called_once()
        self.mock_logger.info.assert_any_call("Successfully connected to Modbus server.")

    @patch('modbus_tcp_proxy.ModbusTcpClient')
    @patch('time.sleep') # Mock time.sleep to speed up retry tests
    def test_connect_retry_then_success(self, mock_sleep, MockModbusClient):
        mock_client_instance = MockModbusClient.return_value
        mock_client_instance.connect.side_effect = [False, False, True] # Fails twice, then succeeds
        mock_client_instance.is_socket_open.side_effect = [False, False, False, True] # Initial, after 1st fail, after 2nd fail, after success

        persistent_client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        result = persistent_client.connect()

        self.assertTrue(result)
        self.assertEqual(mock_client_instance.connect.call_count, 3)
        self.mock_logger.error.assert_any_call(unittest.mock.stringMatching(r"Connection error to Modbus server:.*Retrying in .*s"))
        self.assertEqual(mock_sleep.call_count, 2)


    @patch('modbus_tcp_proxy.ModbusTcpClient')
    @patch('time.sleep')
    def test_connect_max_retries_failed(self, mock_sleep, MockModbusClient):
        mock_client_instance = MockModbusClient.return_value
        mock_client_instance.connect.return_value = False # Always fails
        mock_client_instance.is_socket_open.return_value = False

        persistent_client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        
        with self.assertRaises(Exception): # Pymodbus can raise various things, or our ConnectionError
            persistent_client.connect()

        self.assertEqual(mock_client_instance.connect.call_count, self.modbus_config.max_retries)
        self.mock_logger.critical.assert_called_once_with(
            f"Max retries ({self.modbus_config.max_retries}) reached for connecting to Modbus server. Giving up. Error: Failed to connect to Modbus server."
        )

    @patch('modbus_tcp_proxy.ModbusTcpClient')
    def test_send_request_successful(self, MockModbusClient):
        mock_pymodbus_client = MockModbusClient.return_value
        mock_pymodbus_client.connect.return_value = True
        mock_pymodbus_client.is_socket_open.return_value = True
        
        mock_socket = MagicMock()
        mock_pymodbus_client.socket = mock_socket

        # Modbus TCP header: TID=1, PID=0, Len=6, UID=1
        # PDU: FuncCode=3 (Read Holding Registers), StartAddr=0, Quantity=1
        request_data = b'\x00\x01\x00\x00\x00\x06\x01\x03\x00\x00\x00\x01'
        
        # Response: TID=1, PID=0, Len=5, UID=1
        # PDU: FuncCode=3, ByteCount=2, Value=0x1234
        response_header = b'\x00\x01\x00\x00\x00\x05'
        response_pdu = b'\x01\x03\x02\x12\x34'
        full_response = response_header + response_pdu

        # _read_exact reads header then PDU
        mock_socket.recv.side_effect = [
            response_header, # First call for header
            response_pdu     # Second call for PDU
        ]

        client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        client.connect() # Establish the mocked client
        
        response = client.send_request(request_data)

        mock_socket.sendall.assert_called_once_with(request_data)
        self.assertEqual(mock_socket.recv.call_count, 2)
        self.assertEqual(response, full_response)
        self.mock_logger.debug.assert_any_call(f"Sending request: {request_data.hex()}")
        self.mock_logger.debug.assert_any_call(f"Received response: {full_response.hex()} (Header: {response_header.hex()}, PDU: {response_pdu.hex()})")


    @patch('modbus_tcp_proxy.ModbusTcpClient')
    def test_send_request_socket_error_on_send(self, MockModbusClient):
        mock_pymodbus_client = MockModbusClient.return_value
        mock_pymodbus_client.connect.return_value = True
        mock_pymodbus_client.is_socket_open.return_value = True
        
        mock_socket = MagicMock()
        mock_pymodbus_client.socket = mock_socket
        mock_socket.sendall.side_effect = socket.error("Send failed")

        client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        client.connect()

        request_data = b'\x00\x01\x00\x00\x00\x06\x01\x03\x00\x00\x00\x01'
        with self.assertRaisesRegex(socket.error, "Send failed"):
            client.send_request(request_data)
        self.mock_logger.error.assert_any_call("Communication error during Modbus request/response: Send failed")


    @patch('modbus_tcp_proxy.ModbusTcpClient')
    def test_send_request_socket_timeout_on_recv_header(self, MockModbusClient):
        mock_pymodbus_client = MockModbusClient.return_value
        mock_pymodbus_client.connect.return_value = True
        mock_pymodbus_client.is_socket_open.return_value = True
        
        mock_socket = MagicMock()
        mock_pymodbus_client.socket = mock_socket
        mock_socket.recv.side_effect = socket.timeout("Recv timeout") # Timeout on first recv (header)

        client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        client.connect()

        request_data = b'\x00\x01\x00\x00\x00\x06\x01\x03\x00\x00\x00\x01'
        with self.assertRaisesRegex(socket.timeout, "Recv timeout"):
            client.send_request(request_data)
        
        self.mock_logger.warning.assert_any_call(unittest.mock.stringMatching(r"Socket recv timeout reached while waiting for 6 bytes. Received 0 bytes so far."))
        self.mock_logger.error.assert_any_call("Communication error during Modbus request/response: Recv timeout")

    @patch('modbus_tcp_proxy.ModbusTcpClient')
    def test_send_request_premature_close_on_recv_pdu(self, MockModbusClient):
        mock_pymodbus_client = MockModbusClient.return_value
        mock_pymodbus_client.connect.return_value = True
        mock_pymodbus_client.is_socket_open.return_value = True
        
        mock_socket = MagicMock()
        mock_pymodbus_client.socket = mock_socket

        response_header = b'\x00\x01\x00\x00\x00\x05' # PDU length is 5
        # Premature close, only 3 bytes of PDU received instead of 5
        partial_pdu = b'\x01\x03\x02' 
        
        mock_socket.recv.side_effect = [
            response_header, 
            partial_pdu, # Part of PDU
            b''          # Empty byte string indicating close
        ]

        client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        client.connect()

        request_data = b'\x00\x01\x00\x00\x00\x06\x01\x03\x00\x00\x00\x01'
        with self.assertRaises(ConnectionAbortedError): # As raised by _read_exact
            client.send_request(request_data)

        self.mock_logger.warning.assert_any_call("Modbus server closed connection prematurely while reading response.")
        self.mock_logger.error.assert_any_call(unittest.mock.stringMatching(r"Communication error during Modbus request/response: Modbus server closed connection prematurely."))


    @patch('modbus_tcp_proxy.ModbusTcpClient')
    def test_close_method(self, MockModbusClient):
        mock_client_instance = MockModbusClient.return_value
        mock_client_instance.connect.return_value = True
        mock_client_instance.is_socket_open.return_value = True

        persistent_client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        persistent_client.connect() # Connect to initialize self.client
        
        persistent_client.close()
        mock_client_instance.close.assert_called_once()
        self.mock_logger.info.assert_any_call("Modbus connection closed.")
        self.assertIsNone(persistent_client.client)

    @patch('modbus_tcp_proxy.ModbusTcpClient')
    def test_close_method_error_on_pymodbus_close(self, MockModbusClient):
        mock_client_instance = MockModbusClient.return_value
        mock_client_instance.connect.return_value = True
        mock_client_instance.is_socket_open.return_value = True
        mock_client_instance.close.side_effect = socket.error("Close error")

        persistent_client = PersistentModbusClient(self.modbus_config, self.mock_logger)
        persistent_client.connect()
        
        persistent_client.close() # Should not raise, but log
        mock_client_instance.close.assert_called_once()
        self.mock_logger.warning.assert_called_once_with("Error closing Modbus connection: Close error")
        self.assertIsNone(persistent_client.client) # Should still be reset

# More complex tests for handle_client and process_requests would go here
# These often require more elaborate mocking of sockets and threading primitives

class TestProxyFlow(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.mock_queue = MagicMock(spec=queue.Queue)
        self.mock_stop_event = MagicMock(spec=threading.Event)
        self.mock_active_connections = {}
        self.mock_semaphore = MagicMock(spec=threading.Semaphore)
        
        self.client_socket_mock = MagicMock(spec=socket.socket)
        self.client_address = ('127.0.0.1', 12345)

    def test_handle_client_receives_data_and_queues(self):
        self.mock_stop_event.is_set.side_effect = [False, True] # Run loop once, then stop
        self.client_socket_mock.recv.return_value = b"request_data"

        handle_client(
            self.client_socket_mock, self.client_address, self.mock_queue,
            self.mock_logger, self.mock_stop_event, self.mock_active_connections, self.mock_semaphore
        )

        self.client_socket_mock.recv.assert_called_once_with(DEFAULT_RECV_BUFFER_SIZE)
        self.mock_queue.put.assert_called_once_with(
            (b"request_data", self.client_socket_mock, f"{self.client_address[0]}:{self.client_address[1]}")
        )
        self.client_socket_mock.close.assert_called_once()
        self.mock_semaphore.release.assert_called_once()
        self.assertNotIn(f"{self.client_address[0]}:{self.client_address[1]}", self.mock_active_connections)

    def test_handle_client_disconnect(self):
        self.mock_stop_event.is_set.return_value = False # Loop effectively once due to "no data"
        self.client_socket_mock.recv.return_value = b"" # Empty data means disconnect

        handle_client(
            self.client_socket_mock, self.client_address, self.mock_queue,
            self.mock_logger, self.mock_stop_event, self.mock_active_connections, self.mock_semaphore
        )
        self.mock_logger.info.assert_any_call(f"Client disconnected: {self.client_address[0]}:{self.client_address[1]}")
        self.mock_queue.put.assert_not_called() # No data, so not called
        self.client_socket_mock.close.assert_called_once()

    def test_handle_client_socket_error(self):
        self.mock_stop_event.is_set.return_value = False
        self.client_socket_mock.recv.side_effect = socket.error("Recv error")

        handle_client(
            self.client_socket_mock, self.client_address, self.mock_queue,
            self.mock_logger, self.mock_stop_event, self.mock_active_connections, self.mock_semaphore
        )
        self.mock_logger.error.assert_any_call(f"Socket error with client {self.client_address[0]}:{self.client_address[1]}: Recv error")
        self.mock_queue.put.assert_not_called()
        self.client_socket_mock.close.assert_called_once()

    def test_process_requests_successful(self):
        mock_persistent_client = MagicMock(spec=PersistentModbusClient)
        request_data = b"modbus_request"
        response_data = b"modbus_response"
        connection_id = f"{self.client_address[0]}:{self.client_address[1]}"

        # Simulate one item in queue, then stop
        self.mock_queue.get.side_effect = [(request_data, self.client_socket_mock, connection_id), queue.Empty]
        self.mock_stop_event.is_set.side_effect = [False, True] # After queue.Empty, stop
        
        mock_persistent_client.send_request.return_value = response_data
        self.mock_active_connections[connection_id] = self.client_socket_mock # Client is active
        self.client_socket_mock.fileno.return_value = 1 # Simulate open socket

        process_requests(
            self.mock_queue, mock_persistent_client, self.mock_logger,
            self.mock_stop_event, self.mock_active_connections
        )

        self.mock_queue.get.assert_called_once_with(timeout=1.0)
        mock_persistent_client.send_request.assert_called_once_with(request_data)
        self.client_socket_mock.sendall.assert_called_once_with(response_data)

    def test_process_requests_client_disconnected_before_processing(self):
        mock_persistent_client = MagicMock(spec=PersistentModbusClient)
        request_data = b"modbus_request"
        connection_id = "disconnected_client:1234" # Not in active_connections

        self.mock_queue.get.side_effect = [(request_data, self.client_socket_mock, connection_id), queue.Empty]
        self.mock_stop_event.is_set.side_effect = [False, True]

        process_requests(
            self.mock_queue, mock_persistent_client, self.mock_logger,
            self.mock_stop_event, self.mock_active_connections # Empty active_connections
        )
        self.mock_logger.warning.assert_any_call(f"Client {connection_id} disconnected or socket invalid before processing request. Discarding.")
        mock_persistent_client.send_request.assert_not_called()

    def test_process_requests_error_in_send_request(self):
        mock_persistent_client = MagicMock(spec=PersistentModbusClient)
        request_data = b"modbus_request"
        connection_id = f"{self.client_address[0]}:{self.client_address[1]}"

        self.mock_queue.get.side_effect = [(request_data, self.client_socket_mock, connection_id), queue.Empty]
        self.mock_stop_event.is_set.side_effect = [False, True]
        
        mock_persistent_client.send_request.side_effect = socket.error("Modbus comm error")
        self.mock_active_connections[connection_id] = self.client_socket_mock
        self.client_socket_mock.fileno.return_value = 1

        process_requests(
            self.mock_queue, mock_persistent_client, self.mock_logger,
            self.mock_stop_event, self.mock_active_connections
        )
        self.mock_logger.error.assert_any_call(f"Communication error processing request for {connection_id}: Modbus comm error. Client may be disconnected.")
        self.client_socket_mock.sendall.assert_not_called()
        self.client_socket_mock.close.assert_called_once() # Should close client socket on error
        self.assertNotIn(connection_id, self.mock_active_connections)


# Example of how start_server tests might begin (very complex to fully unit test)
class TestStartServerBehavior(unittest.TestCase):

    def get_minimal_config(self):
        return {
            'Proxy': {'ServerHost': '127.0.0.1', 'ServerPort': 50299, 'AllowedIPs': [], 'MaxConnections': 2, 'ListenBacklog':1},
            'ModbusServer': {'ModbusServerHost': '1.2.3.4', 'ModbusServerPort': 502, 'ConnectionTimeout':1, 'MaxRetries':1},
            'Logging': {'Enable': False}
        }

    @patch('modbus_tcp_proxy.socket.socket')
    @patch('modbus_tcp_proxy.PersistentModbusClient')
    @patch('modbus_tcp_proxy.ThreadPoolExecutor')
    @patch('modbus_tcp_proxy.init_logger') # Ensure logger is mocked
    @patch('modbus_tcp_proxy.signal.signal') # Mock signal registration
    def test_start_server_ip_not_allowed(self, mock_signal, mock_init_logger, MockThreadPoolExecutor, MockPersistentModbusClient, MockSocket):
        config = self.get_minimal_config()
        config['Proxy']['AllowedIPs'] = ['10.0.0.1'] # Only allow 10.0.0.1

        mock_server_socket_instance = MockSocket.return_value.__enter__.return_value
        
        # Simulate a connection from a disallowed IP
        mock_client_socket = MagicMock()
        client_address = ('192.168.1.10', 12345) # This IP is not allowed
        mock_server_socket_instance.accept.side_effect = [(mock_client_socket, client_address), socket.timeout] # Accept once, then timeout to stop

        # Mock stop_event to control the loop
        with patch('threading.Event') as MockEvent:
            mock_event_instance = MockEvent.return_value
            mock_event_instance.is_set.side_effect = [False, True] # Loop once for accept, then stop

            start_server(config)
        
        mock_client_socket.close.assert_called_once() # Socket from disallowed IP should be closed
        logger_instance = mock_init_logger.return_value
        logger_instance.warning.assert_any_call(f"Connection from {client_address[0]} (address: {ipaddress.ip_address(client_address[0])}) not allowed. Closing connection.")
        MockThreadPoolExecutor.return_value.__enter__.return_value.submit.assert_not_called() # No client should be handled


    @patch('modbus_tcp_proxy.socket.socket')
    @patch('modbus_tcp_proxy.PersistentModbusClient')
    @patch('modbus_tcp_proxy.ThreadPoolExecutor')
    @patch('modbus_tcp_proxy.init_logger')
    @patch('modbus_tcp_proxy.signal.signal')
    @patch('modbus_tcp_proxy.connection_semaphore.acquire') # Direct patch of the semaphore instance used in start_server
    def test_start_server_max_connections_reached(self, mock_semaphore_acquire, mock_signal, mock_init_logger, MockThreadPoolExecutor, MockPersistentModbusClient, MockSocket):
        config = self.get_minimal_config()
        config['Proxy']['MaxConnections'] = 1 # Set very low for test

        mock_server_socket_instance = MockSocket.return_value.__enter__.return_value
        
        mock_client_socket1 = MagicMock()
        client_address1 = ('127.0.0.1', 12345)
        
        mock_client_socket2 = MagicMock()
        client_address2 = ('127.0.0.1', 12346)

        # Semaphore: first acquire is True, second is False (max connections reached)
        # This needs to be patched on the actual semaphore instance if not passed around.
        # For simplicity, if connection_semaphore was a global or easily accessible:
        # For this test, we assume connection_semaphore is created inside start_server
        # and we need to mock its creation or behavior. The current test setup will be tricky.
        # A better way would be to have Semaphore passed or created in a mockable way.
        # Let's try mocking the Semaphore class itself for this specific test.
        
        with patch('threading.Semaphore') as MockSemaphore:
            mock_sem_instance = MockSemaphore.return_value
            mock_sem_instance.acquire.side_effect = [True, False] # First connection allowed, second rejected

            mock_server_socket_instance.accept.side_effect = [
                (mock_client_socket1, client_address1), 
                (mock_client_socket2, client_address2), 
                socket.timeout # Stop after two attempts
            ]
            
            with patch('threading.Event') as MockEvent:
                mock_event_instance = MockEvent.return_value
                mock_event_instance.is_set.side_effect = [False, False, True] 

                start_server(config)

            MockSemaphore.assert_called_once_with(config['Proxy']['MaxConnections'])
            
            # First client should be submitted
            MockThreadPoolExecutor.return_value.__enter__.return_value.submit.assert_any_call(
                handle_client, mock_client_socket1, client_address1, unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY, mock_sem_instance
            )
            # Second client socket should be closed
            mock_client_socket2.close.assert_called_once()
            logger_instance = mock_init_logger.return_value
            logger_instance.warning.assert_any_call(f"Maximum connections ({config['Proxy']['MaxConnections']}) reached. Connection from {client_address2[0]} rejected.")


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)

# Note: Some tests like max_connections might be more complex due to how semaphore is instantiated.
# The provided test for max_connections attempts to mock threading.Semaphore.
# For full integration tests of start_server, a different approach (e.g., actual threading and socket usage on localhost)
# might be needed, but that goes beyond typical unit tests.
# Added import for 'queue' and 'threading' for TestProxyFlow
import queue 
import threading
import socket # For socket.error etc. in PersistentModbusClient tests.
```

**Key aspects of the created test file:**

1.  **Imports and Setup:**
    *   Imports necessary modules from `modbus_tcp_proxy.py` and `unittest`, `unittest.mock`.
    *   `sys.path.insert` is used to allow the test file to import the main script from the parent directory. This is a common pattern for simple project structures.
    *   Logging is disabled globally during tests.

2.  **`TestConfigValidation`:**
    *   Tests `validate_network_settings` for valid/invalid IPs and hostnames.
    *   Tests `validate_config` with a base valid configuration and introduces specific invalid values (port, missing fields, type errors) to check for `ValueError`.
    *   Tests environment variable overrides using `@patch.dict(os.environ, ...)`.
    *   Tests `load_config` by mocking `open` and the `validate_config` call itself.

3.  **`TestPersistentModbusClient`:**
    *   Uses `@patch('modbus_tcp_proxy.ModbusTcpClient')` to mock the actual `pymodbus` client.
    *   **Connection:** Tests successful connection, retry logic (mocking `time.sleep`), and failure after max retries.
    *   **`send_request`:**
        *   Tests a successful scenario, ensuring data is sent and the response is correctly constructed from header and PDU based on the new logic. `socket.recv` is mocked to return header and PDU parts sequentially.
        *   Tests handling of `socket.error` on send.
        *   Tests `socket.timeout` during header reception.
        *   Tests `ConnectionAbortedError` (premature close by server) during PDU reception.
    *   **`close`:** Tests that the underlying `pymodbus` client's `close` is called and that errors during this close are logged but don't crash.

4.  **`TestProxyFlow` (Simplified client/server interactions):**
    *   This class focuses on `handle_client` and `process_requests`.
    *   **`handle_client`:**
        *   Tests that received data is put onto the queue.
        *   Tests client disconnection (empty data from `recv`).
        *   Tests socket errors during `recv`.
    *   **`process_requests`:**
        *   Tests successful processing: item from queue -> `persistent_client.send_request` -> response sent back via client socket.
        *   Tests scenario where client is no longer in `active_connections`.
        *   Tests error handling when `persistent_client.send_request` fails.

5.  **`TestStartServerBehavior` (More conceptual/edge cases for `start_server`):**
    *   These are more high-level and mock out major components like `socket.socket`, `ThreadPoolExecutor`, and `PersistentModbusClient`.
    *   **IP Not Allowed:** Simulates a client connecting from an IP not in `AllowedIPs`. Checks that the client socket is closed and no handler is submitted to the thread pool.
    *   **Max Connections Reached:** This test is more complex due to the `Semaphore` being instantiated within `start_server`. The test attempts to mock `threading.Semaphore` itself to control its behavior. It checks that after the max number of connections, subsequent connections are rejected and their sockets closed.

6.  **Running Tests:**
    *   The `if __name__ == '__main__':` block allows running the tests directly. `argv` and `exit=False` are common for running in some environments.

**To run these tests (conceptually, as I cannot run them here):**

```bash
python -m unittest tests/test_modbus_tcp_proxy.py
```

Or, if the `tests` directory is recognized as a package:

```bash
python -m unittest discover tests
```

This set of tests covers the requested functionalities. The `start_server` tests are more high-level due to the complexity of mocking threaded server environments but demonstrate testing specific logic paths like IP allowance and connection limits.The test file `tests/test_modbus_tcp_proxy.py` has been created with a comprehensive set of unit tests covering configuration, `PersistentModbusClient`, and aspects of the proxy flow and server behavior as requested.

I will now submit the report.
