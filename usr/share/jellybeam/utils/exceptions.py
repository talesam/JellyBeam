# utils/exceptions.py
"""
Custom exception hierarchy for JellyBeam application.

This module defines all custom exceptions used throughout the application,
providing better error context and enabling more specific exception handling.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class JellyBeamError(Exception):
    """Base exception for all JellyBeam errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize JellyBeamError.

        Args:
            message: Human-readable error message
            details: Additional error context/details
        """
        self.message: str = message
        self.details: Dict[str, Any] = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


# Docker-related errors


class DockerError(JellyBeamError):
    """Base exception for Docker-related errors."""

    pass


class DockerNotInstalledError(DockerError):
    """Docker is not installed on the system."""

    def __init__(self) -> None:
        super().__init__("Docker is not installed on this system")


class DockerNotRunningError(DockerError):
    """Docker daemon is not running."""

    def __init__(self) -> None:
        super().__init__("Docker daemon is not running")


class DockerImageError(DockerError):
    """Error pulling or managing Docker images."""

    def __init__(
        self,
        image_name: str,
        operation: str = "pull",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        message = f"Failed to {operation} Docker image: {image_name}"
        super().__init__(message, details)


class DockerContainerError(DockerError):
    """Error creating or managing Docker containers."""

    def __init__(
        self,
        container_name: str,
        operation: str = "create",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        message = f"Failed to {operation} Docker container: {container_name}"
        super().__init__(message, details)


class DockerCommandError(DockerError):
    """Error executing command in Docker container."""

    def __init__(
        self,
        command: str,
        exit_code: Optional[int] = None,
        stderr: Optional[str] = None,
    ) -> None:
        message = f"Docker command failed: {command}"
        details: Dict[str, Any] = {}
        if exit_code is not None:
            details["exit_code"] = exit_code
        if stderr:
            details["stderr"] = stderr
        super().__init__(message, details)


# Device-related errors


class DeviceError(JellyBeamError):
    """Base exception for device-related errors."""

    pass


class DeviceNotFoundError(DeviceError):
    """Device not found on network."""

    def __init__(self, ip_address: Optional[str] = None) -> None:
        if ip_address:
            message = f"Device not found at IP: {ip_address}"
        else:
            message = "No Samsung devices found on network"
        super().__init__(message)


class DeviceConnectionError(DeviceError):
    """Failed to connect to device."""

    def __init__(self, ip_address: str, reason: Optional[str] = None) -> None:
        message = f"Failed to connect to device at {ip_address}"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class SDBError(DeviceError):
    """Samsung Debug Bridge (SDB) errors."""

    def __init__(
        self, operation: str, details: Optional[Dict[str, Any]] = None
    ) -> None:
        message = f"SDB operation failed: {operation}"
        super().__init__(message, details)


class DeviceNotReachableError(DeviceError):
    """Device is not reachable on the network."""

    def __init__(self, ip_address: str, port: Optional[int] = None) -> None:
        message = f"Device not reachable at {ip_address}"
        if port:
            message += f":{port}"
        super().__init__(message)


# Certificate-related errors


class CertificateError(JellyBeamError):
    """Base exception for certificate-related errors."""

    pass


class CertificateValidationError(CertificateError):
    """Certificate validation failed."""

    def __init__(
        self, cert_type: str = "certificate", reason: Optional[str] = None
    ) -> None:
        message = f"{cert_type.capitalize()} validation failed"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class CertificatePasswordError(CertificateError):
    """Invalid certificate password."""

    def __init__(self) -> None:
        super().__init__("Invalid certificate password")


class CertificateCompatibilityError(CertificateError):
    """Certificates are not compatible."""

    def __init__(self, reason: Optional[str] = None) -> None:
        message = "Certificates are not compatible for Tizen development"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class CertificateNotFoundError(CertificateError):
    """Certificate file not found."""

    def __init__(self, cert_path: str) -> None:
        super().__init__(f"Certificate file not found: {cert_path}")


class CertificateFormatError(CertificateError):
    """Invalid certificate file format."""

    def __init__(self, cert_path: str, expected_format: str = "P12") -> None:
        message = f"Invalid certificate format: {cert_path}"
        super().__init__(message, {"expected": expected_format})


# Network-related errors


class NetworkError(JellyBeamError):
    """Base exception for network-related errors."""

    pass


class NetworkScanError(NetworkError):
    """Network scanning failed."""

    def __init__(self, reason: Optional[str] = None) -> None:
        message = "Network scan failed"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class NetworkTimeoutError(NetworkError):
    """Network operation timed out."""

    def __init__(self, operation: str, timeout: int) -> None:
        message = f"Network timeout during {operation}"
        super().__init__(message, {"timeout_seconds": timeout})


# Validation errors


class ValidationError(JellyBeamError):
    """Input validation errors."""

    def __init__(self, field: str, value: Any, reason: Optional[str] = None) -> None:
        message = f"Validation failed for {field}: {value}"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class IPAddressValidationError(ValidationError):
    """Invalid IP address format."""

    def __init__(self, ip_address: str) -> None:
        super().__init__("IP address", ip_address, "Invalid format")


class PortValidationError(ValidationError):
    """Invalid port number."""

    def __init__(self, port: int) -> None:
        super().__init__("port", port, "Must be between 1 and 65535")


class PathValidationError(ValidationError):
    """Invalid file or directory path."""

    def __init__(self, path: str, reason: Optional[str] = None) -> None:
        super().__init__("path", path, reason)


# Configuration errors


class ConfigurationError(JellyBeamError):
    """Base exception for configuration-related errors."""

    pass


class ConfigLoadError(ConfigurationError):
    """Failed to load configuration file."""

    def __init__(self, config_path: str, reason: Optional[str] = None) -> None:
        message = f"Failed to load configuration: {config_path}"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class ConfigSaveError(ConfigurationError):
    """Failed to save configuration file."""

    def __init__(self, config_path: str, reason: Optional[str] = None) -> None:
        message = f"Failed to save configuration: {config_path}"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


# Installation errors


class InstallationError(JellyBeamError):
    """Base exception for installation-related errors."""

    pass


class SDKInstallationError(InstallationError):
    """Tizen SDK installation failed."""

    def __init__(self, reason: Optional[str] = None) -> None:
        message = "Tizen SDK installation failed"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class AppBuildError(InstallationError):
    """Application build failed."""

    def __init__(self, reason: Optional[str] = None) -> None:
        message = "Application build failed"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


class AppInstallError(InstallationError):
    """Application installation to device failed."""

    def __init__(self, device_ip: str, reason: Optional[str] = None) -> None:
        message = f"Failed to install application to device {device_ip}"
        details = {"reason": reason} if reason else None
        super().__init__(message, details)


# Server customization errors


class CustomizationError(JellyBeamError):
    """Base exception for server-customization errors."""

    pass


class CustomizationURLError(CustomizationError):
    """The configured Jellyfin server URL cannot be used."""

    def __init__(self, url: str, reason: Optional[str] = None) -> None:
        message = "Invalid Jellyfin server URL"
        details = {"url": url} if url else {}
        if reason:
            details["reason"] = reason
        super().__init__(message, details or None)


class CustomizationInjectionError(CustomizationError):
    """Could not inject the customization tags into index.html."""

    def __init__(self, reason: str) -> None:
        super().__init__("Customization injection failed", {"reason": reason})
