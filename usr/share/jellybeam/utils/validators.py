# utils/validators.py
"""Input validation utilities for JellyBeam."""

from __future__ import annotations

import re
import ipaddress
import os
from typing import Union


class NetworkValidator:
    """Validates network-related inputs."""

    @staticmethod
    def is_valid_ip(ip_string: str) -> bool:
        """Validate IP address format."""
        try:
            ipaddress.ip_address(ip_string)
            return True
        except ValueError:
            return False

    @staticmethod
    def is_valid_port(port: Union[int, str]) -> bool:
        """Validate port number."""
        try:
            port_num = int(port)
            return 1 <= port_num <= 65535
        except (ValueError, TypeError):
            return False

    @staticmethod
    def is_valid_port_range(port_range: str) -> bool:
        """Validate port range format (e.g., '8000-8080')."""
        try:
            if "-" not in port_range:
                return NetworkValidator.is_valid_port(port_range)

            start, end = port_range.split("-", 1)
            start_port = int(start.strip())
            end_port = int(end.strip())

            return (
                NetworkValidator.is_valid_port(start_port)
                and NetworkValidator.is_valid_port(end_port)
                and start_port <= end_port
            )
        except (ValueError, AttributeError):
            return False


class FileValidator:
    """Validates file-related inputs."""

    @staticmethod
    def is_valid_p12_file(file_path: str) -> bool:
        """Check if file exists and has .p12 extension."""
        if not os.path.exists(file_path):
            return False

        return file_path.lower().endswith(".p12")

    @staticmethod
    def is_readable_file(file_path: str) -> bool:
        """Check if file exists and is readable."""
        return os.path.isfile(file_path) and os.access(file_path, os.R_OK)

    @staticmethod
    def get_file_size(file_path: str) -> int:
        """Get file size in bytes."""
        try:
            return os.path.getsize(file_path)
        except OSError:
            return 0


class CertificateValidator:
    """Validates certificate-related inputs."""

    @staticmethod
    def is_valid_profile_name(name: str) -> bool:
        """Validate profile name format."""
        if not name or len(name.strip()) == 0:
            return False

        # Profile names should be alphanumeric with optional spaces, dashes, underscores
        pattern = r"^[a-zA-Z0-9\s\-_]+$"
        return bool(re.match(pattern, name.strip()))

    @staticmethod
    def is_strong_password(password: str) -> bool:
        """Check if password meets minimum strength requirements."""
        if len(password) < 6:
            return False

        # At least one letter and one number
        has_letter = bool(re.search(r"[a-zA-Z]", password))
        has_number = bool(re.search(r"\d", password))

        return has_letter and has_number


class DockerValidator:
    """Validates Docker-related inputs."""

    @staticmethod
    def is_valid_image_name(image_name: str) -> bool:
        """Validate Docker image name format.

        Supports formats:
        - repository:tag
        - namespace/repository:tag
        - registry.example.com/namespace/repository:tag
        - localhost:5000/namespace/repository:tag
        """
        if not image_name:
            return False

        # Docker image name validation supporting:
        # - Optional registry with port (localhost:5000, registry.io:443)
        # - Optional namespace/repository path
        # - Optional tag or digest
        pattern = r"^([a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?(:[0-9]+)?/)?([a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?(/[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?)*)(:[\w][\w.-]*|@sha256:[a-fA-F0-9]{64})?$"
        return bool(re.match(pattern, image_name))

    @staticmethod
    def is_valid_container_name(name: str) -> bool:
        """Validate Docker container name format."""
        if not name:
            return False

        # Container names must be alphanumeric with optional dashes and underscores
        pattern = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"
        return bool(re.match(pattern, name))
