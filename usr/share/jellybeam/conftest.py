# conftest.py
"""
Pytest configuration and global fixtures.

This module provides reusable test fixtures for the JellyBeam test suite.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import sys
import tempfile
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def mock_config_manager():
    """Mock ConfigManager for testing."""
    mock = Mock()

    # Default return values
    mock.get.return_value = None
    mock.set.return_value = None
    mock.get_all.return_value = {}

    # Simulate dot notation access
    def get_side_effect(key, default=None):
        config_values = {
            "docker.container_name": "jellybeam-builder",
            "docker.image": "jellybeam/tizen-builder:latest",
            "docker.workspace_path": "/tmp/jellybeam",
            "network.scan_timeout": 30,
            "network.max_workers": 30,
            "timeouts.docker_operations": 300,
            "timeouts.network_scan": 30,
            "logging.level": "INFO",
        }
        return config_values.get(key, default)

    mock.get.side_effect = get_side_effect

    return mock


@pytest.fixture
def mock_logger():
    """Mock Logger for testing."""
    mock = Mock()
    mock.info = Mock()
    mock.error = Mock()
    mock.warning = Mock()
    mock.debug = Mock()
    mock.exception = Mock()
    return mock


@pytest.fixture
def mock_glib():
    """Mock GLib.idle_add for testing async callbacks."""

    def idle_add(callback, *args, **kwargs):
        """Immediately call the callback instead of scheduling it."""
        callback(*args, **kwargs)
        return True

    mock = Mock()
    mock.idle_add = Mock(side_effect=idle_add)
    return mock


@pytest.fixture
def temp_config_file():
    """Create a temporary configuration file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        config_data = {
            "device": {"ip": "192.168.1.100", "developer_mode": True},
            "docker": {"image": "test-image:latest"},
            "network": {"scan_timeout": 30},
        }
        json.dump(config_data, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def temp_directory():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for testing shell commands."""
    with patch("subprocess.run") as mock_run:
        # Default successful return
        mock_run.return_value = Mock(returncode=0, stdout="success", stderr="")
        yield mock_run


@pytest.fixture
def mock_socket():
    """Mock socket for network testing."""
    with patch("socket.socket") as mock_sock_class:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0  # Success
        mock_sock.getsockname.return_value = ("192.168.1.100", 12345)
        mock_sock_class.return_value = mock_sock
        yield mock_sock


@pytest.fixture
def sample_device_data():
    """Sample device data for testing."""
    return {
        "ip": "192.168.1.50",
        "port": 8001,
        "name": "Samsung TV",
        "model": "UE50NU7400",
        "os": "Tizen",
    }


@pytest.fixture
def mock_certificate_data():
    """Mock certificate data for testing."""
    return {
        "author_cert_path": "/path/to/author.p12",
        "distributor_cert_path": "/path/to/distributor.p12",
        "password": "test_password",
        "profile_name": "TestProfile",
    }


@pytest.fixture(autouse=True)
def reset_mocks():
    """Automatically reset all mocks between tests."""
    yield
    # Cleanup happens automatically due to fixture scope
