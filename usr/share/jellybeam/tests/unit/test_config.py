# tests/unit/test_config.py
"""
Unit tests for configuration management.
"""

import json
from utils.config import ConfigManager


class TestConfigManager:
    """Test ConfigManager class."""

    def test_default_config_structure(self, temp_directory):
        """Test that default configuration has all required keys."""
        # Create config in temp directory
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        # Check main sections
        assert "device" in config._config
        assert "certificates" in config._config
        assert "docker" in config._config
        assert "network" in config._config
        assert "timeouts" in config._config
        assert "ui" in config._config
        assert "logging" in config._config

    def test_get_with_dot_notation(self, temp_directory):
        """Test getting values using dot notation."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        # Test getting nested values
        assert config.get("docker.container_name") == "jellybeam-builder"
        assert config.get("network.scan_timeout") == 30
        assert config.get("logging.level") == "INFO"

    def test_get_with_default(self, temp_directory):
        """Test getting non-existent key returns default."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        assert config.get("nonexistent.key", "default_value") == "default_value"
        assert config.get("device.nonexistent", None) is None

    def test_set_with_dot_notation(self, temp_directory):
        """Test setting values using dot notation."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        config.set("device.ip", "192.168.1.100")
        assert config.get("device.ip") == "192.168.1.100"

        config.set("network.scan_timeout", 60)
        assert config.get("network.scan_timeout") == 60

    def test_get_all(self, temp_directory):
        """Test getting all configuration."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        all_config = config.get_all()
        assert isinstance(all_config, dict)
        assert "device" in all_config
        assert "docker" in all_config

    def test_reset_to_defaults(self, temp_directory):
        """Test resetting configuration to defaults."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        # Modify config
        config.set("device.ip", "192.168.1.100")
        assert config.get("device.ip") == "192.168.1.100"

        # Reset
        config.reset_to_defaults()
        assert config.get("device.ip") == ""

    def test_export_config(self, temp_directory):
        """Test exporting configuration to file."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        export_path = temp_directory / "exported.json"
        config.export_config(str(export_path))

        assert export_path.exists()
        with open(export_path, "r") as f:
            exported_data = json.load(f)
        assert "device" in exported_data

    def test_import_config(self, temp_directory):
        """Test importing configuration from file."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        # Create import file
        import_data = {
            "device": {"ip": "10.0.0.1", "developer_mode": True},
            "logging": {"level": "DEBUG"},
        }
        import_path = temp_directory / "import.json"
        with open(import_path, "w") as f:
            json.dump(import_data, f)

        # Import
        config.import_config(str(import_path))
        assert config.get("device.ip") == "10.0.0.1"
        assert config.get("device.developer_mode") is True
        assert config.get("logging.level") == "DEBUG"
