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
    def test_start_docker_asks_through_pkexec_not_sudo(
        self, mock_glib, mock_run, docker_service
    ):
        """The reported bug: sudo's prompt went to a pipe and never showed.

        sudo needs a terminal. Captured, its prompt is invisible and the app
        hangs; pkexec puts up the desktop's own dialog instead.
        """
        mock_run.return_value = Mock(returncode=0, stderr="")
        done = threading.Event()
        mock_glib.idle_add.side_effect = lambda fn, *a, **kw: done.set()

        docker_service.start_docker_async(Mock())
        done.wait(timeout=2)

        chamadas = [c.args[0] for c in mock_run.call_args_list if c.args]
        primeira = chamadas[0]
        assert primeira[0] == "pkexec", primeira
        assert "sudo" not in primeira, primeira
        # One prompt, not one per fallback.
        assert primeira[1:3] == ["sh", "-c"]
        assert "||" in primeira[3]

    @patch("subprocess.run")
    @patch("services.docker.GLib")
    def test_start_docker_says_when_the_dialog_is_dismissed(
        self, mock_glib, mock_run, docker_service
    ):
        """Cancelling the password dialog must explain itself, not fail mutely."""
        mock_run.return_value = Mock(returncode=126, stderr="")
        recebido = []
        done = threading.Event()

        def capture(fn, *a, **kw):
            recebido.append(a)
            done.set()

        mock_glib.idle_add.side_effect = capture
        docker_service.start_docker_async(Mock())
        done.wait(timeout=2)

        assert recebido, "callback never ran"
        ok, mensagem = recebido[0][0], recebido[0][1]
        assert ok is False
        assert mensagem, "a dismissed dialog must come with a reason"

    @patch("subprocess.run", side_effect=FileNotFoundError)
    @patch("services.docker.GLib")
    def test_start_docker_survives_missing_pkexec(
        self, mock_glib, mock_run, docker_service
    ):
        """No polkit agent is a plausible setup; it must not raise."""
        recebido = []
        done = threading.Event()

        def capture(fn, *a, **kw):
            recebido.append(a)
            done.set()

        mock_glib.idle_add.side_effect = capture
        docker_service.start_docker_async(Mock())
        done.wait(timeout=2)

        assert recebido and recebido[0][0] is False

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


class TestCertificateDecision:
    """Only Tizen 8+ gets its own certificate.

    Earlier versions install the published package as published, which is
    faster and long proven. Generating a certificate for them would change
    a working path for no gain.
    """

    @pytest.fixture
    def docker_service(self, mock_logger):
        return DockerService(logger=mock_logger)

    @pytest.mark.parametrize("version", ["6.5", "7.0", "7.6"])
    def test_older_tizen_uses_the_published_package(self, version, docker_service):
        assert docker_service.needs_own_certificate(version) is False

    @pytest.mark.parametrize("version", ["8.0", "9.0", "10.1"])
    def test_tizen_8_and_newer_need_their_own(self, version, docker_service):
        # 10.1 matters: compared as text it sorts below "8".
        assert docker_service.needs_own_certificate(version) is True

    @pytest.mark.parametrize("version", ["", None, "unknown", "x.y"])
    def test_unreadable_version_keeps_the_old_path(self, version, docker_service):
        # Guessing "needs a certificate" here would break every TV whose
        # version we simply failed to read.
        assert docker_service.needs_own_certificate(version) is False
