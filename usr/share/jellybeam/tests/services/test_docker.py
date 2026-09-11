# tests/services/test_docker.py
"""Tests for Docker service."""

import threading

import pytest
from unittest.mock import Mock, patch
import subprocess

from services.docker import DockerService
from utils.exceptions import DockerError


class TestDockerService:
    """Tests for DockerService class."""

    @pytest.fixture
    def docker_service(self):
        """Create a DockerService instance with a mock logger."""
        mock_logger = Mock()
        return DockerService(logger=mock_logger)

    def test_init_default_logger(self):
        """Test initialization with default logger."""
        service = DockerService()
        assert service.logger is not None
        assert service.container_name is not None
        assert service.image_name is not None

    def test_init_custom_logger(self, docker_service):
        """Test initialization with custom logger."""
        assert docker_service.logger is not None

    @patch("subprocess.run")
    def test_is_docker_installed_true(self, mock_run, docker_service):
        """Test Docker installation check when installed."""
        mock_run.return_value = Mock(returncode=0)
        assert docker_service.is_docker_installed() is True
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_is_docker_installed_false(self, mock_run, docker_service):
        """Test Docker installation check when not installed."""
        mock_run.return_value = Mock(returncode=1)
        assert docker_service.is_docker_installed() is False

    @patch("subprocess.run")
    def test_is_docker_installed_timeout(self, mock_run, docker_service):
        """Test Docker installation check on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        assert docker_service.is_docker_installed() is False

    @patch("subprocess.run")
    def test_is_docker_installed_not_found(self, mock_run, docker_service):
        """Test Docker installation check when docker not found."""
        mock_run.side_effect = FileNotFoundError()
        assert docker_service.is_docker_installed() is False

    @patch("subprocess.run")
    def test_is_docker_running_true(self, mock_run, docker_service):
        """Test Docker running check when running."""
        mock_run.return_value = Mock(returncode=0)
        assert docker_service.is_docker_running() is True

    @patch("subprocess.run")
    def test_is_docker_running_false(self, mock_run, docker_service):
        """Test Docker running check when not running."""
        mock_run.return_value = Mock(returncode=1)
        assert docker_service.is_docker_running() is False

    @patch("subprocess.run")
    def test_is_docker_running_timeout(self, mock_run, docker_service):
        """Test Docker running check on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        assert docker_service.is_docker_running() is False

    @patch("subprocess.run")
    def test_stop_all_processes(self, mock_run, docker_service):
        """Test stopping all Docker processes."""
        mock_run.return_value = Mock(returncode=0)
        docker_service.stop_all_processes()
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_stop_all_processes_timeout(self, mock_run, docker_service):
        """Test stopping processes on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        # Should not raise, just log warning
        docker_service.stop_all_processes()

    def test_install_docker_unsupported_distro(self, docker_service):
        """Test Docker installation for unsupported distribution."""
        with pytest.raises(DockerError):
            docker_service.install_docker("unsupported_distro")


class TestDockerServiceAsync:
    """Tests for DockerService async methods."""

    @pytest.fixture
    def docker_service(self):
        """Create a DockerService instance with a mock logger."""
        mock_logger = Mock()
        return DockerService(logger=mock_logger)

    @patch("subprocess.run")
    @patch("services.docker.GLib")
    def test_start_docker_async_success(self, mock_glib, mock_run, docker_service):
        """Test starting Docker asynchronously."""
        mock_run.return_value = Mock(returncode=0)
        mock_callback = Mock()

        # Call the async method
        done = threading.Event()
        mock_glib.idle_add.side_effect = lambda fn, *a, **kw: done.set()
        docker_service.start_docker_async(mock_callback)
        done.wait(timeout=2)

    @patch("subprocess.run")
    @patch("services.docker.GLib")
    def test_prepare_environment_async(self, mock_glib, mock_run, docker_service):
        """Test preparing Docker environment."""
        mock_run.return_value = Mock(returncode=0)
        mock_callback = Mock()

        done = threading.Event()
        mock_glib.idle_add.side_effect = lambda fn, *a, **kw: done.set()
        docker_service.prepare_environment_async(mock_callback)
        done.wait(timeout=2)
