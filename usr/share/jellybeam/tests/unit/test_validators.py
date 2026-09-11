# tests/unit/test_validators.py
"""
Unit tests for validator utilities.
"""

from utils.validators import (
    NetworkValidator,
    FileValidator,
    CertificateValidator,
    DockerValidator,
)


class TestNetworkValidator:
    """Test NetworkValidator class."""

    def test_valid_ipv4_addresses(self):
        """Test validation of valid IPv4 addresses."""
        valid_ips = [
            "192.168.1.1",
            "8.8.8.8",
            "10.0.0.1",
            "255.255.255.255",
            "0.0.0.0",
            "127.0.0.1",
        ]
        for ip in valid_ips:
            assert NetworkValidator.is_valid_ip(ip), f"{ip} should be valid"

    def test_invalid_ip_addresses(self):
        """Test validation of invalid IP addresses."""
        invalid_ips = [
            "256.1.1.1",  # Out of range
            "192.168.1",  # Incomplete
            "192.168.1.1.1",  # Too many octets
            "invalid",  # Not numeric
            "",  # Empty string
            "192.168.-1.1",  # Negative number
            "192.168.1.a",  # Non-numeric
        ]
        for ip in invalid_ips:
            assert not NetworkValidator.is_valid_ip(ip), f"{ip} should be invalid"

    def test_valid_ports(self):
        """Test validation of valid port numbers."""
        valid_ports = [1, 80, 443, 8001, 8080, 65535]
        for port in valid_ports:
            assert NetworkValidator.is_valid_port(port), f"Port {port} should be valid"

    def test_invalid_ports(self):
        """Test validation of invalid port numbers."""
        invalid_ports = [0, -1, 65536, 70000, "invalid", None, ""]
        for port in invalid_ports:
            assert not NetworkValidator.is_valid_port(port), (
                f"Port {port} should be invalid"
            )

    def test_valid_port_ranges(self):
        """Test validation of valid port ranges."""
        valid_ranges = [
            "8000-8080",
            "1-65535",
            "443-443",
            "8001",  # Single port
        ]
        for port_range in valid_ranges:
            assert NetworkValidator.is_valid_port_range(port_range), (
                f"Range {port_range} should be valid"
            )

    def test_invalid_port_ranges(self):
        """Test validation of invalid port ranges."""
        invalid_ranges = [
            "8080-8000",  # Start > End
            "0-100",  # Start is 0
            "100-70000",  # End too large
            "invalid-range",
            "100-",
            "-100",
            "",
        ]
        for port_range in invalid_ranges:
            assert not NetworkValidator.is_valid_port_range(port_range), (
                f"Range {port_range} should be invalid"
            )


class TestFileValidator:
    """Test FileValidator class."""

    def test_valid_p12_file(self, temp_directory):
        """Test validation of valid P12 certificate files."""
        # Create a temporary P12 file
        p12_file = temp_directory / "test_cert.p12"
        p12_file.write_text("fake certificate data")

        assert FileValidator.is_valid_p12_file(str(p12_file))

    def test_invalid_p12_file_wrong_extension(self, temp_directory):
        """Test that non-P12 files are rejected."""
        txt_file = temp_directory / "test.txt"
        txt_file.write_text("not a certificate")

        assert not FileValidator.is_valid_p12_file(str(txt_file))

    def test_invalid_p12_file_not_exists(self):
        """Test that non-existent files are rejected."""
        assert not FileValidator.is_valid_p12_file("/nonexistent/path/cert.p12")

    def test_readable_file(self, temp_directory):
        """Test validation of readable files."""
        test_file = temp_directory / "readable.txt"
        test_file.write_text("test content")

        assert FileValidator.is_readable_file(str(test_file))

    def test_unreadable_file(self):
        """Test validation rejects non-existent files."""
        assert not FileValidator.is_readable_file("/nonexistent/file.txt")

    def test_get_file_size(self, temp_directory):
        """Test getting file size."""
        test_file = temp_directory / "sized.txt"
        content = "test content"
        test_file.write_text(content)

        size = FileValidator.get_file_size(str(test_file))
        assert size == len(content.encode())

    def test_get_file_size_nonexistent(self):
        """Test getting size of nonexistent file returns 0."""
        assert FileValidator.get_file_size("/nonexistent/file.txt") == 0


class TestCertificateValidator:
    """Test CertificateValidator class."""

    def test_valid_profile_names(self):
        """Test validation of valid profile names."""
        valid_names = [
            "JellyBeam",
            "MyProfile",
            "Test_Profile",
            "Profile-Name",
            "Profile 123",
            "ProfileName123",
        ]
        for name in valid_names:
            assert CertificateValidator.is_valid_profile_name(name), (
                f"'{name}' should be valid"
            )

    def test_invalid_profile_names(self):
        """Test validation of invalid profile names."""
        invalid_names = [
            "",  # Empty
            "   ",  # Only spaces
            "Profile@Name",  # Special characters
            "Profile!",
            "Profile#123",
            None,  # Will cause len() to fail, caught by empty check
        ]
        for name in invalid_names:
            assert not CertificateValidator.is_valid_profile_name(name), (
                f"'{name}' should be invalid"
            )

    def test_strong_passwords(self):
        """Test validation of strong passwords."""
        strong_passwords = [
            "password123",
            "Test123",
            "abc123def",
            "P@ssw0rd",
            "SecurePass1",
        ]
        for password in strong_passwords:
            assert CertificateValidator.is_strong_password(password), (
                f"'{password}' should be strong"
            )

    def test_weak_passwords(self):
        """Test validation rejects weak passwords."""
        weak_passwords = [
            "pass",  # Too short
            "12345",  # Too short
            "password",  # No numbers
            "12345678",  # No letters
            "",  # Empty
            "abc",  # Too short, no numbers
        ]
        for password in weak_passwords:
            assert not CertificateValidator.is_strong_password(password), (
                f"'{password}' should be weak"
            )


class TestDockerValidator:
    """Test DockerValidator class."""

    def test_valid_image_names(self):
        """Test validation of valid Docker image names."""
        valid_images = [
            "ubuntu",
            "ubuntu:20.04",
            "myregistry/myimage",
            "myregistry/namespace/image:tag",
            "jellybeam/tizen-builder:latest",
            "localhost:5000/myimage:v1.0",
        ]
        for image in valid_images:
            assert DockerValidator.is_valid_image_name(image), (
                f"'{image}' should be valid"
            )

    def test_invalid_image_names(self):
        """Test validation of invalid Docker image names."""
        invalid_images = [
            "",  # Empty
            "Invalid Image",  # Spaces
            "invalid@image",  # Invalid characters
            "image::",  # Double colon
            ":tag",  # Missing image name
        ]
        for image in invalid_images:
            assert not DockerValidator.is_valid_image_name(image), (
                f"'{image}' should be invalid"
            )

    def test_valid_container_names(self):
        """Test validation of valid Docker container names."""
        valid_names = [
            "mycontainer",
            "jellybeam-builder",
            "container_name",
            "container.name",
            "container123",
            "my-container_123.test",
        ]
        for name in valid_names:
            assert DockerValidator.is_valid_container_name(name), (
                f"'{name}' should be valid"
            )

    def test_invalid_container_names(self):
        """Test validation of invalid Docker container names."""
        invalid_names = [
            "",  # Empty
            "-mycontainer",  # Starts with dash
            "_mycontainer",  # Starts with underscore
            "my container",  # Contains space
            "my@container",  # Invalid character
            "My_Container!",  # Invalid character
        ]
        for name in invalid_names:
            assert not DockerValidator.is_valid_container_name(name), (
                f"'{name}' should be invalid"
            )
