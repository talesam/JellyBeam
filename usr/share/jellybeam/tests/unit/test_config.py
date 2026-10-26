# tests/unit/test_config.py
"""
Unit tests for configuration management.
"""

import json
import os
import stat

import pytest

from utils.config import ConfigManager


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """ConfigManager() reads ~/.config/jellybeam: never the developer's own."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


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
        assert set(config._config) == {"device", "certificates", "customization", "logging"}
        # Keys nothing read (image, timeouts, window size...) are gone.
        assert "docker" not in config._config and "network" not in config._config

    def test_get_with_dot_notation(self, temp_directory):
        """Test getting values using dot notation."""
        config = ConfigManager()
        config.config_dir = temp_directory
        config.config_file = temp_directory / "config.json"
        config._config = config._default_config()

        # Test getting nested values
        assert config.get("certificates.use_default") is True
        assert config.get("customization.enabled") is False
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
        assert "customization" in all_config

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


class TestLoadAndSave:
    def _arquivo(self):
        return ConfigManager().config_file

    def test_file_values_win_and_missing_keys_get_defaults(self):
        arquivo = self._arquivo()
        arquivo.write_text(json.dumps({"device": {"ip": "10.0.0.7"}, "legacy": {"x": 1}}))
        config = ConfigManager()
        assert config.get("device.ip") == "10.0.0.7"
        assert config.get("certificates.use_default") is True  # absent from the file
        assert config.get("legacy.x") == 1  # unknown keys are kept, not dropped

    def test_an_unreadable_file_is_set_aside_not_overwritten(self):
        arquivo = self._arquivo()
        arquivo.write_text('{"device": {"ip": "10.0.0.7"')  # truncated
        config = ConfigManager()
        assert config.get("device.ip") == ""
        reserva = arquivo.with_suffix(".json.broken")
        assert reserva.read_text().startswith('{"device"')
        config.set("logging.level", "DEBUG")
        assert reserva.exists()  # the user's data survives the next save

    def test_saved_atomically_and_private(self):
        config = ConfigManager()
        config.set("customization.server_url", "https://example.org")
        assert stat.S_IMODE(os.stat(config.config_file).st_mode) == 0o600
        assert json.loads(config.config_file.read_text())["customization"]["server_url"] == "https://example.org"
        assert not [p for p in os.listdir(config.config_dir) if p.startswith(".config-")]

    def test_get_returns_a_copy_of_sections(self):
        config = ConfigManager()
        secao = config.get("device")
        secao["ip"] = "mudado"
        assert config.get("device.ip") == ""
