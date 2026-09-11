# utils/config.py
from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Dict

_logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages application configuration using JSON files."""

    # Previous project name; settings live here for anyone who installed
    # before the rename to JellyBeam.
    LEGACY_CONFIG_DIR: Path = Path.home() / ".config" / "jellytizen"

    def __init__(self) -> None:
        self.config_dir: Path = Path.home() / ".config" / "jellybeam"
        self.config_file: Path = self.config_dir / "config.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        self._migrate_legacy_config()
        self._config: Dict[str, Any] = self._load_config()

    def _migrate_legacy_config(self) -> None:
        """Copy the pre-rename config over, once, if we have none yet.

        Copy rather than move: if the new version misbehaves the user can
        still downgrade and find their settings where they left them.
        """
        legacy_file = self.LEGACY_CONFIG_DIR / "config.json"
        if self.config_file.exists() or not legacy_file.is_file():
            return

        try:
            shutil.copy2(legacy_file, self.config_file)
        except OSError as e:
            # Not fatal: we just start from defaults.
            _logger.warning(f"Could not migrate config from {legacy_file}: {e}")
        else:
            _logger.info(f"Migrated configuration from {legacy_file}")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return self._default_config()
        else:
            return self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "device": {"ip": "", "developer_mode": False, "last_connected": None},
            "certificates": {
                "use_default": True,  # Use built-in certificates from Docker container
                "author_cert_path": "",
                "distributor_cert_path": "",
                "profile_name": "JellyBeam",
            },
            "docker": {
                "image": "ghcr.io/georift/install-jellyfin-tizen:latest",
                "auto_pull": True,
                "container_name": "jellybeam-builder",
                "workspace_path": "/tmp/jellybeam",
            },
            # Tags pointing at a Jellyfin server, embedded into the TV build.
            # The URL stays here, in the user's config, and never in the
            # repository -- it is a private address and this repo is public.
            "customization": {
                "enabled": False,
                "server_url": "",
            },
            "network": {
                "scan_timeout": 30,
                "port_range": "8000-8080",
                "max_workers": 30,
                "connection_timeout": 10,
            },
            "timeouts": {
                "docker_operations": 300,
                "network_scan": 30,
                "device_connection": 10,
                "certificate_validation": 30,
                "sdk_setup": 600,
            },
            "ui": {"window_width": 900, "window_height": 700, "theme": "auto"},
            "logging": {"level": "INFO", "save_to_file": True, "max_log_age_days": 30},
            "advanced": {"custom_scripts": False, "debug_mode": False},
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value using dot notation."""
        with self._lock:
            keys = key.split(".")
            config = self._config

            # Navigate to the parent of the target key
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]

            # Set the value
            config[keys[-1]] = value

            # Save configuration
            self._save_config()

    def _save_config(self) -> None:
        """Save configuration to file."""
        try:
            with open(self.config_file, "w") as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            _logger.error(f"Failed to save config: {e}")

    def reset_to_defaults(self) -> None:
        """Reset configuration to default values."""
        self._config = self._default_config()
        self._save_config()

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values."""
        return self._config.copy()

    def export_config(self, file_path: str) -> None:
        """Export configuration to a file."""
        with open(file_path, "w") as f:
            json.dump(self._config, f, indent=2)

    def import_config(self, file_path: str) -> None:
        """Import configuration from a file."""
        with open(file_path, "r") as f:
            imported_config = json.load(f)

        # Merge with default config to ensure all keys exist
        default_config = self._default_config()
        self._merge_configs(default_config, imported_config)

        self._config = default_config
        self._save_config()

    def _merge_configs(self, base: Dict[str, Any], overlay: Dict[str, Any]) -> None:
        """Recursively merge two configuration dictionaries."""
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_configs(base[key], value)
            else:
                base[key] = value
