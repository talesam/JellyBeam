# tests/unit/test_exceptions.py
"""
Unit tests for custom exceptions.
"""

from utils.exceptions import (
    JellyBeamError,
    DockerError,
    DockerNotInstalledError,
    DockerNotRunningError,
    DockerImageError,
    DockerContainerError,
    DeviceError,
    DeviceNotFoundError,
    DeviceConnectionError,
    CertificateError,
    CertificateValidationError,
    CertificatePasswordError,
    NetworkError,
    NetworkScanError,
    ValidationError,
    IPAddressValidationError,
)


class TestBaseException:
    """Test base JellyBeamError exception."""

    def test_basic_message(self):
        """Test exception with just a message."""
        exc = JellyBeamError("Test error")
        assert str(exc) == "Test error"
        assert exc.message == "Test error"
        assert exc.details == {}

    def test_message_with_details(self):
        """Test exception with message and details."""
        exc = JellyBeamError("Test error", details={"key": "value", "code": 123})
        assert "Test error" in str(exc)
        assert "key=value" in str(exc)
        assert "code=123" in str(exc)


class TestDockerExceptions:
    """Test Docker-related exceptions."""

    def test_docker_not_installed(self):
        """Test DockerNotInstalledError."""
        exc = DockerNotInstalledError()
        assert "Docker is not installed" in str(exc)
        assert isinstance(exc, DockerError)
        assert isinstance(exc, JellyBeamError)

    def test_docker_not_running(self):
        """Test DockerNotRunningError."""
        exc = DockerNotRunningError()
        assert "not running" in str(exc)
        assert isinstance(exc, DockerError)

    def test_docker_image_error(self):
        """Test DockerImageError."""
        exc = DockerImageError("myimage:latest", operation="pull")
        assert "pull" in str(exc)
        assert "myimage:latest" in str(exc)
        assert isinstance(exc, DockerError)

    def test_docker_container_error(self):
        """Test DockerContainerError."""
        exc = DockerContainerError("mycontainer", operation="create")
        assert "create" in str(exc)
        assert "mycontainer" in str(exc)
        assert isinstance(exc, DockerError)


class TestDeviceExceptions:
    """Test device-related exceptions."""

    def test_device_not_found_with_ip(self):
        """Test DeviceNotFoundError with IP address."""
        exc = DeviceNotFoundError(ip_address="192.168.1.100")
        assert "192.168.1.100" in str(exc)
        assert isinstance(exc, DeviceError)

    def test_device_not_found_without_ip(self):
        """Test DeviceNotFoundError without IP address."""
        exc = DeviceNotFoundError()
        assert "No Samsung devices" in str(exc)

    def test_device_connection_error(self):
        """Test DeviceConnectionError."""
        exc = DeviceConnectionError("192.168.1.100", reason="timeout")
        assert "192.168.1.100" in str(exc)
        assert isinstance(exc, DeviceError)


class TestCertificateExceptions:
    """Test certificate-related exceptions."""

    def test_certificate_validation_error(self):
        """Test CertificateValidationError."""
        exc = CertificateValidationError(cert_type="author", reason="expired")
        assert "Author" in str(exc)
        assert isinstance(exc, CertificateError)

    def test_certificate_password_error(self):
        """Test CertificatePasswordError."""
        exc = CertificatePasswordError()
        assert "password" in str(exc).lower()
        assert isinstance(exc, CertificateError)


class TestNetworkExceptions:
    """Test network-related exceptions."""

    def test_network_scan_error(self):
        """Test NetworkScanError."""
        exc = NetworkScanError(reason="timeout")
        assert "scan failed" in str(exc).lower()
        assert isinstance(exc, NetworkError)


class TestValidationExceptions:
    """Test validation exceptions."""

    def test_validation_error(self):
        """Test generic ValidationError."""
        exc = ValidationError("username", "admin", reason="too short")
        assert "username" in str(exc)
        assert "admin" in str(exc)

    def test_ip_address_validation_error(self):
        """Test IPAddressValidationError."""
        exc = IPAddressValidationError("999.999.999.999")
        assert "999.999.999.999" in str(exc)
        assert isinstance(exc, ValidationError)
