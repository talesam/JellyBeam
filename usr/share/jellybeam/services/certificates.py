# services/certificates.py
import os
import threading
import subprocess
from gi.repository import GLib
from cryptography.hazmat.primitives.serialization import pkcs12
from utils.logger import Logger
from utils.constants import CERT_FILE_EXTENSION, TIMEOUT_CERTIFICATE_VALIDATION
from utils.exceptions import (
    CertificateValidationError,
    CertificatePasswordError,
    CertificateCompatibilityError,
    CertificateNotFoundError,
    CertificateFormatError,
)


class CertificateService:
    """Service for certificate management and validation."""

    def __init__(self, logger=None):
        """
        Initialize Certificate service.

        Args:
            logger (Logger, optional): Logger instance. Creates new one if not provided.
        """
        self.logger = logger or Logger()

    def validate_certificates_async(
        self, author_cert_path, dist_cert_path, password, callback
    ):
        """Validate certificates asynchronously."""

        def validate():
            try:
                self.logger.info("Starting certificate validation")

                # Validate author certificate
                if not self._validate_p12_file(author_cert_path, password):
                    error_msg = "Invalid author certificate or password"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)
                    return

                self.logger.info("Author certificate validated successfully")

                # Validate distributor certificate
                if not self._validate_p12_file(dist_cert_path, ""):
                    error_msg = "Invalid distributor certificate"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)
                    return

                self.logger.info("Distributor certificate validated successfully")

                # Check certificate compatibility
                if not self._check_certificate_compatibility(
                    author_cert_path, dist_cert_path, password
                ):
                    error_msg = "Certificates are not compatible"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)
                    return

                self.logger.info("Certificates are compatible")
                GLib.idle_add(callback, True, "Certificates validated successfully")

            except CertificatePasswordError as e:
                self.logger.error(f"Certificate password error: {e}")
                GLib.idle_add(callback, False, str(e))
            except CertificateValidationError as e:
                self.logger.error(f"Certificate validation error: {e}")
                GLib.idle_add(callback, False, str(e))
            except Exception as e:
                self.logger.exception(f"Unexpected error validating certificates: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=validate, daemon=True)
        thread.start()

    def _validate_p12_file(self, cert_path, password):
        """Validate a P12 certificate file."""
        try:
            # Check if file exists
            if not os.path.exists(cert_path):
                self.logger.error(f"Certificate file not found: {cert_path}")
                raise CertificateNotFoundError(cert_path)

            # Check file extension
            if not cert_path.lower().endswith(CERT_FILE_EXTENSION):
                self.logger.error(f"Invalid certificate format: {cert_path}")
                raise CertificateFormatError(cert_path)

            self.logger.debug(f"Validating certificate: {cert_path}")

            with open(cert_path, "rb") as f:
                cert_data = f.read()

            # Try to load the certificate
            password_bytes = password.encode("utf-8") if password else None

            private_key, certificate, additional_certificates = (
                pkcs12.load_key_and_certificates(cert_data, password_bytes)
            )

            is_valid = private_key is not None and certificate is not None
            if is_valid:
                self.logger.debug(f"Certificate validated: {cert_path}")
            else:
                self.logger.warning(f"Certificate validation failed: {cert_path}")

            return is_valid

        except ValueError as e:
            # This usually means incorrect password
            self.logger.error(f"Certificate load error (likely wrong password): {e}")
            raise CertificatePasswordError()
        except FileNotFoundError:
            self.logger.error(f"Certificate file not found: {cert_path}")
            raise CertificateNotFoundError(cert_path)
        except Exception as e:
            self.logger.exception(f"Error validating certificate {cert_path}: {e}")
            raise CertificateValidationError("certificate", reason=str(e))

    def _check_certificate_compatibility(self, author_cert, dist_cert, password):
        """Check if certificates are compatible for Tizen development."""
        try:
            self.logger.debug("Checking certificate compatibility")

            # Load both certificates
            with open(author_cert, "rb") as f:
                author_data = f.read()

            with open(dist_cert, "rb") as f:
                dist_data = f.read()

            password_bytes = password.encode("utf-8") if password else None

            # Load author certificate
            try:
                author_key, author_cert_obj, _ = pkcs12.load_key_and_certificates(
                    author_data, password_bytes
                )
            except ValueError as e:
                self.logger.error(f"Failed to load author certificate: {e}")
                raise CertificatePasswordError()

            # Load distributor certificate (usually no password)
            try:
                dist_key, dist_cert_obj, _ = pkcs12.load_key_and_certificates(
                    dist_data, None
                )
            except ValueError as e:
                self.logger.error(f"Failed to load distributor certificate: {e}")
                raise CertificateValidationError("distributor", reason=str(e))

            # Check if certificates are for Tizen development
            # This is a basic check - in reality, you'd verify the certificate chain
            # and ensure they're properly signed by Samsung

            author_subject = author_cert_obj.subject.rfc4514_string()
            dist_subject = dist_cert_obj.subject.rfc4514_string()

            self.logger.debug(f"Author subject: {author_subject}")
            self.logger.debug(f"Distributor subject: {dist_subject}")

            # Basic validation that these look like Tizen certificates
            is_compatible = "Samsung" in dist_subject and len(author_subject) > 0

            if is_compatible:
                self.logger.info("Certificates are compatible")
            else:
                self.logger.warning("Certificates may not be compatible")

            return is_compatible

        except CertificatePasswordError:
            raise  # Re-raise specific exceptions
        except CertificateValidationError:
            raise  # Re-raise specific exceptions
        except FileNotFoundError as e:
            self.logger.error(f"Certificate file not found: {e}")
            raise CertificateNotFoundError(str(e))
        except Exception as e:
            self.logger.exception(f"Error checking certificate compatibility: {e}")
            raise CertificateCompatibilityError(reason=str(e))

    def extract_certificate_info(self, cert_path, password=""):
        """Extract information from a certificate file."""
        try:
            self.logger.debug(f"Extracting info from certificate: {cert_path}")

            if not os.path.exists(cert_path):
                self.logger.error(f"Certificate not found: {cert_path}")
                raise CertificateNotFoundError(cert_path)

            with open(cert_path, "rb") as f:
                cert_data = f.read()

            password_bytes = password.encode("utf-8") if password else None

            private_key, certificate, additional_certificates = (
                pkcs12.load_key_and_certificates(cert_data, password_bytes)
            )

            if certificate:
                info = {
                    "subject": certificate.subject.rfc4514_string(),
                    "issuer": certificate.issuer.rfc4514_string(),
                    "not_valid_before": certificate.not_valid_before_utc,
                    "not_valid_after": certificate.not_valid_after_utc,
                    "serial_number": str(certificate.serial_number),
                }

                self.logger.info(f"Certificate info extracted for {cert_path}")
                return info

            self.logger.warning(f"No certificate found in {cert_path}")
            return None

        except ValueError as e:
            self.logger.error(
                f"Failed to extract certificate info (wrong password?): {e}"
            )
            raise CertificatePasswordError()
        except FileNotFoundError:
            self.logger.error(f"Certificate file not found: {cert_path}")
            raise CertificateNotFoundError(cert_path)
        except Exception as e:
            self.logger.exception(f"Error extracting certificate info: {e}")
            raise CertificateValidationError("certificate", reason=str(e))

    def create_tizen_profile(self, profile_name, author_cert, password, workspace_path):
        """Create a Tizen security profile."""
        try:
            self.logger.info(f"Creating Tizen profile: {profile_name}")

            profile_cmd = [
                "tizen",
                "security-profiles",
                "add",
                "-n",
                profile_name,
                "-a",
                author_cert,
                "-p",
                password,
            ]

            result = subprocess.run(
                profile_cmd,
                capture_output=True,
                text=True,
                cwd=workspace_path,
                timeout=TIMEOUT_CERTIFICATE_VALIDATION,
            )

            if result.returncode == 0:
                self.logger.info(f"Tizen profile created successfully: {profile_name}")
                return True
            else:
                self.logger.error(f"Failed to create Tizen profile: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout creating Tizen profile: {profile_name}")
            return False
        except FileNotFoundError:
            self.logger.error("Tizen CLI not found")
            return False
        except Exception as e:
            self.logger.exception(f"Error creating Tizen profile: {e}")
            return False
