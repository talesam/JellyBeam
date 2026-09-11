# tests/services/test_certificates.py
"""Tests for Certificate service."""

import pytest
from unittest.mock import Mock, patch, mock_open

from services.certificates import CertificateService
from utils.exceptions import (
    CertificateNotFoundError,
    CertificatePasswordError,
    CertificateFormatError,
    CertificateValidationError,
)


class TestCertificateService:
    """Tests for CertificateService class."""

    @pytest.fixture
    def cert_service(self):
        """Create a CertificateService instance with a mock logger."""
        mock_logger = Mock()
        return CertificateService(logger=mock_logger)

    def test_init_default_logger(self):
        """Test initialization with default logger."""
        service = CertificateService()
        assert service.logger is not None

    def test_init_custom_logger(self, cert_service):
        """Test initialization with custom logger."""
        assert cert_service.logger is not None


class TestCertificateValidation:
    """Tests for certificate validation methods."""

    @pytest.fixture
    def cert_service(self):
        """Create a CertificateService instance with a mock logger."""
        mock_logger = Mock()
        return CertificateService(logger=mock_logger)

    def test_validate_p12_file_not_found(self, cert_service):
        """Test validation when file doesn't exist."""
        with pytest.raises((CertificateNotFoundError, CertificateValidationError)):
            cert_service._validate_p12_file("/nonexistent/path/cert.p12", "password")

    def test_validate_p12_file_wrong_extension(self, cert_service, tmp_path):
        """Test validation with wrong file extension."""
        # Create a temp file with wrong extension
        wrong_ext_file = tmp_path / "cert.txt"
        wrong_ext_file.write_text("not a certificate")

        with pytest.raises((CertificateFormatError, CertificateValidationError)):
            cert_service._validate_p12_file(str(wrong_ext_file), "password")

    @patch("builtins.open", mock_open(read_data=b"fake cert data"))
    @patch("services.certificates.pkcs12.load_key_and_certificates")
    def test_validate_p12_file_success(self, mock_load, cert_service, tmp_path):
        """Test successful P12 validation."""
        # Create a temp file with correct extension
        cert_file = tmp_path / "cert.p12"
        cert_file.write_bytes(b"fake cert data")

        mock_load.return_value = (Mock(), Mock(), [])

        result = cert_service._validate_p12_file(str(cert_file), "password")
        assert result is True

    @patch("builtins.open", mock_open(read_data=b"fake cert data"))
    @patch("services.certificates.pkcs12.load_key_and_certificates")
    def test_validate_p12_file_wrong_password(self, mock_load, cert_service, tmp_path):
        """Test validation with wrong password."""
        cert_file = tmp_path / "cert.p12"
        cert_file.write_bytes(b"fake cert data")

        mock_load.side_effect = ValueError("Wrong password")

        with pytest.raises(CertificatePasswordError):
            cert_service._validate_p12_file(str(cert_file), "wrong_password")

    @patch("builtins.open", mock_open(read_data=b"fake cert data"))
    @patch("services.certificates.pkcs12.load_key_and_certificates")
    def test_validate_p12_file_no_key(self, mock_load, cert_service, tmp_path):
        """Test validation when no private key found."""
        cert_file = tmp_path / "cert.p12"
        cert_file.write_bytes(b"fake cert data")

        mock_load.return_value = (None, Mock(), [])

        result = cert_service._validate_p12_file(str(cert_file), "password")
        assert result is False


class TestCertificateCompatibility:
    """Tests for certificate compatibility checking."""

    @pytest.fixture
    def cert_service(self):
        """Create a CertificateService instance with a mock logger."""
        mock_logger = Mock()
        return CertificateService(logger=mock_logger)

    @patch("builtins.open", mock_open(read_data=b"fake cert data"))
    @patch("services.certificates.pkcs12.load_key_and_certificates")
    def test_check_compatibility_success(self, mock_load, cert_service, tmp_path):
        """Test compatibility check success."""
        author_cert = tmp_path / "author.p12"
        dist_cert = tmp_path / "distributor.p12"
        author_cert.write_bytes(b"fake")
        dist_cert.write_bytes(b"fake")

        # Mock author certificate
        mock_author_cert = Mock()
        mock_author_cert.subject.rfc4514_string.return_value = "CN=Test Author"

        # Mock distributor certificate with Samsung in subject
        mock_dist_cert = Mock()
        mock_dist_cert.subject.rfc4514_string.return_value = "CN=Samsung Electronics"

        mock_load.side_effect = [
            (Mock(), mock_author_cert, []),
            (Mock(), mock_dist_cert, []),
        ]

        result = cert_service._check_certificate_compatibility(
            str(author_cert), str(dist_cert), "password"
        )
        assert result is True

    @patch("builtins.open", mock_open(read_data=b"fake cert data"))
    @patch("services.certificates.pkcs12.load_key_and_certificates")
    def test_check_compatibility_not_samsung(self, mock_load, cert_service, tmp_path):
        """Test compatibility check when distributor is not Samsung."""
        author_cert = tmp_path / "author.p12"
        dist_cert = tmp_path / "distributor.p12"
        author_cert.write_bytes(b"fake")
        dist_cert.write_bytes(b"fake")

        mock_author_cert = Mock()
        mock_author_cert.subject.rfc4514_string.return_value = "CN=Test Author"

        mock_dist_cert = Mock()
        mock_dist_cert.subject.rfc4514_string.return_value = "CN=Other Company"

        mock_load.side_effect = [
            (Mock(), mock_author_cert, []),
            (Mock(), mock_dist_cert, []),
        ]

        result = cert_service._check_certificate_compatibility(
            str(author_cert), str(dist_cert), "password"
        )
        assert result is False


class TestCertificateExtraction:
    """Tests for certificate info extraction."""

    @pytest.fixture
    def cert_service(self):
        """Create a CertificateService instance with a mock logger."""
        mock_logger = Mock()
        return CertificateService(logger=mock_logger)

    def test_extract_info_file_not_found(self, cert_service):
        """Test extraction when file doesn't exist."""
        with pytest.raises((CertificateNotFoundError, CertificateValidationError)):
            cert_service.extract_certificate_info("/nonexistent/cert.p12")

    @patch("builtins.open", mock_open(read_data=b"fake cert data"))
    @patch("services.certificates.pkcs12.load_key_and_certificates")
    def test_extract_info_success(self, mock_load, cert_service, tmp_path):
        """Test successful info extraction."""
        cert_file = tmp_path / "cert.p12"
        cert_file.write_bytes(b"fake cert data")

        mock_cert = Mock()
        mock_cert.subject.rfc4514_string.return_value = "CN=Test"
        mock_cert.issuer.rfc4514_string.return_value = "CN=Issuer"
        mock_cert.not_valid_before_utc = "2024-01-01"
        mock_cert.not_valid_after_utc = "2025-01-01"
        mock_cert.serial_number = 12345

        mock_load.return_value = (Mock(), mock_cert, [])

        result = cert_service.extract_certificate_info(str(cert_file))
        assert result is not None
        assert "subject" in result
        assert "issuer" in result

    @patch("builtins.open", mock_open(read_data=b"fake cert data"))
    @patch("services.certificates.pkcs12.load_key_and_certificates")
    def test_extract_info_wrong_password(self, mock_load, cert_service, tmp_path):
        """Test extraction with wrong password."""
        cert_file = tmp_path / "cert.p12"
        cert_file.write_bytes(b"fake cert data")

        mock_load.side_effect = ValueError("Wrong password")

        with pytest.raises(CertificatePasswordError):
            cert_service.extract_certificate_info(str(cert_file), "wrong")


class TestTizenProfile:
    """Tests for Tizen profile creation."""

    @pytest.fixture
    def cert_service(self):
        """Create a CertificateService instance with a mock logger."""
        mock_logger = Mock()
        return CertificateService(logger=mock_logger)

    @patch("subprocess.run")
    def test_create_tizen_profile_success(self, mock_run, cert_service, tmp_path):
        """Test successful profile creation."""
        mock_run.return_value = Mock(returncode=0)

        result = cert_service.create_tizen_profile(
            "test_profile", str(tmp_path / "author.p12"), "password", str(tmp_path)
        )
        assert result is True

    @patch("subprocess.run")
    def test_create_tizen_profile_failure(self, mock_run, cert_service, tmp_path):
        """Test profile creation failure."""
        mock_run.return_value = Mock(returncode=1, stderr="Error")

        result = cert_service.create_tizen_profile(
            "test_profile", str(tmp_path / "author.p12"), "password", str(tmp_path)
        )
        assert result is False

    @patch("subprocess.run")
    def test_create_tizen_profile_timeout(self, mock_run, cert_service, tmp_path):
        """Test profile creation on timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tizen", timeout=30)

        result = cert_service.create_tizen_profile(
            "test_profile", str(tmp_path / "author.p12"), "password", str(tmp_path)
        )
        assert result is False

    @patch("subprocess.run")
    def test_create_tizen_profile_cli_not_found(self, mock_run, cert_service, tmp_path):
        """Test when Tizen CLI is not found."""
        mock_run.side_effect = FileNotFoundError()

        result = cert_service.create_tizen_profile(
            "test_profile", str(tmp_path / "author.p12"), "password", str(tmp_path)
        )
        assert result is False
