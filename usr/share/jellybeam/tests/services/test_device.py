# tests/services/test_device.py
"""Tests for Device service."""

import threading

import pytest
from unittest.mock import Mock, patch
import socket
import subprocess

from services.device import DeviceService


class TestDeviceService:
    """Tests for DeviceService class."""

    @pytest.fixture
    def device_service(self):
        """Create a DeviceService instance with a mock logger."""
        mock_logger = Mock()
        return DeviceService(logger=mock_logger)

    def test_init_default_logger(self):
        """Test initialization with default logger."""
        service = DeviceService()
        assert service.logger is not None
        assert service.connected_device is None

    def test_init_custom_logger(self, device_service):
        """Test initialization with custom logger."""
        assert device_service.logger is not None
        assert device_service.connected_device is None

    @patch("socket.socket")
    def test_get_local_ip_success(self, mock_socket_class, device_service):
        """Test getting local IP address."""
        mock_socket = Mock()
        mock_socket.getsockname.return_value = ("192.168.1.100", 0)
        mock_socket_class.return_value = mock_socket

        ip = device_service._get_local_ip()
        assert ip == "192.168.1.100"
        mock_socket.close.assert_called_once()

    @patch("socket.socket")
    def test_get_local_ip_timeout(self, mock_socket_class, device_service):
        """Test getting local IP on timeout."""
        mock_socket = Mock()
        mock_socket.connect.side_effect = socket.timeout()
        mock_socket_class.return_value = mock_socket

        ip = device_service._get_local_ip()
        assert ip is None

    @patch("socket.socket")
    def test_get_local_ip_error(self, mock_socket_class, device_service):
        """Test getting local IP on socket error."""
        mock_socket = Mock()
        mock_socket.connect.side_effect = socket.error("Connection error")
        mock_socket_class.return_value = mock_socket

        ip = device_service._get_local_ip()
        assert ip is None

    @patch("subprocess.run")
    def test_ping_quick_success(self, mock_run, device_service):
        """Test quick ping success."""
        mock_run.return_value = Mock(returncode=0)
        assert device_service._ping_quick("192.168.1.1") is True

    @patch("subprocess.run")
    def test_ping_quick_failure(self, mock_run, device_service):
        """Test quick ping failure."""
        mock_run.return_value = Mock(returncode=1)
        assert device_service._ping_quick("192.168.1.1") is False

    @patch("subprocess.run")
    def test_ping_quick_timeout(self, mock_run, device_service):
        """Test quick ping timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ping", timeout=1)
        assert device_service._ping_quick("192.168.1.1") is False

    @patch("subprocess.run")
    def test_ping_quick_not_found(self, mock_run, device_service):
        """Test quick ping when ping not found."""
        mock_run.side_effect = FileNotFoundError()
        assert device_service._ping_quick("192.168.1.1") is False

    @patch("socket.socket")
    def test_check_port_quick_open(self, mock_socket_class, device_service):
        """Test port check when port is open."""
        mock_socket = Mock()
        mock_socket.connect_ex.return_value = 0
        mock_socket_class.return_value = mock_socket

        assert device_service._check_port_quick("192.168.1.1", 8001) is True
        mock_socket.close.assert_called_once()

    @patch("socket.socket")
    def test_check_port_quick_closed(self, mock_socket_class, device_service):
        """Test port check when port is closed."""
        mock_socket = Mock()
        mock_socket.connect_ex.return_value = 1
        mock_socket_class.return_value = mock_socket

        assert device_service._check_port_quick("192.168.1.1", 8001) is False

    @patch("socket.socket")
    def test_check_port_quick_timeout(self, mock_socket_class, device_service):
        """Test port check on timeout."""
        mock_socket = Mock()
        mock_socket.connect_ex.side_effect = socket.timeout()
        mock_socket_class.return_value = mock_socket

        assert device_service._check_port_quick("192.168.1.1", 8001) is False

    def test_is_connected_false(self, device_service):
        """Test connection status when not connected."""
        assert device_service.is_connected() is False

    def test_is_connected_true(self, device_service):
        """Test connection status when connected."""
        device_service.connected_device = "192.168.1.100"
        assert device_service.is_connected() is True

    def test_disconnect_no_device(self, device_service):
        """Test disconnect when no device connected."""
        device_service.disconnect()
        assert device_service.connected_device is None

    @patch("subprocess.run")
    def test_disconnect_with_device(self, mock_run, device_service):
        """Test disconnect when device is connected."""
        device_service.connected_device = "192.168.1.100"
        mock_run.return_value = Mock(returncode=0)

        device_service.disconnect()
        assert device_service.connected_device is None


class TestDeviceServiceAsync:
    """Tests for DeviceService async methods."""

    @pytest.fixture
    def device_service(self):
        """Create a DeviceService instance with a mock logger."""
        mock_logger = Mock()
        return DeviceService(logger=mock_logger)

    @patch.object(DeviceService, "_get_local_ip")
    @patch("services.device.GLib")
    def test_scan_network_async_no_ip(self, mock_glib, mock_get_ip, device_service):
        """Test network scan when local IP cannot be determined."""
        mock_get_ip.return_value = None
        mock_callback = Mock()

        done = threading.Event()
        mock_glib.idle_add.side_effect = lambda fn, *a, **kw: done.set()
        device_service.scan_network_async(mock_callback)
        done.wait(timeout=2)

    @patch.object(DeviceService, "_check_port_quick")
    @patch("services.device.GLib")
    def test_connect_device_async_unreachable(
        self, mock_glib, mock_port, device_service
    ):
        """Test connection when device is unreachable."""
        mock_port.return_value = False
        mock_callback = Mock()

        done = threading.Event()
        mock_glib.idle_add.side_effect = lambda fn, *a, **kw: done.set()
        device_service.connect_device_async("192.168.1.100", False, mock_callback)
        done.wait(timeout=2)


class TestDeviceServiceIdentification:
    """Tests for Samsung device identification."""

    @pytest.fixture
    def device_service(self):
        """Create a DeviceService instance with a mock logger."""
        mock_logger = Mock()
        return DeviceService(logger=mock_logger)

    @patch("urllib.request.urlopen")
    def test_identify_samsung_device_success(self, mock_urlopen, device_service):
        """Test Samsung device identification success."""
        mock_response = Mock()
        mock_response.status = 200
        mock_response.read.return_value = (
            b'{"device": {"name": "Samsung TV", "modelName": "UN55TU8000"}}'
        )
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = device_service._identify_samsung_device("192.168.1.100", 8001)
        assert result is not None
        assert "name" in result

    @patch("urllib.request.urlopen")
    def test_identify_samsung_device_not_samsung(self, mock_urlopen, device_service):
        """Test identification when device is not Samsung."""
        mock_response = Mock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"device": {"name": "Other TV"}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = device_service._identify_samsung_device("192.168.1.100", 8001)
        # Should return None if no Samsung indicators found
        assert result is None

    @patch("urllib.request.urlopen")
    def test_identify_samsung_device_timeout(self, mock_urlopen, device_service):
        """Test identification on timeout."""
        mock_urlopen.side_effect = socket.timeout()

        result = device_service._identify_samsung_device("192.168.1.100", 8001)
        assert result is None
