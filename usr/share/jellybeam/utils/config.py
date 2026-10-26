# utils/config.py
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

_logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages application configuration using JSON files."""

    def __init__(self) -> None:
        # Previous project name; settings live here for anyone who installed
        # before the rename to JellyBeam. Resolved here, not at import, so it
        # follows the same home as config_dir.
        self.legacy_config_dir: Path = Path.home() / ".config" / "jellytizen"
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
        legacy_file = self.legacy_config_dir / "config.json"
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
        """Load the file over the defaults, so keys added later have values.

        A file that cannot be read is set aside, not silently replaced: the
        next set() would otherwise overwrite the user's settings with the
        defaults.
        """
        config = self._default_config()
        if not self.config_file.exists():
            return config
        try:
            with open(self.config_file, "r") as f:
                carregado = json.load(f)
            if not isinstance(carregado, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError) as e:
            reserva = self.config_file.with_suffix(".json.broken")
            try:
                os.replace(self.config_file, reserva)
                _logger.warning(f"Unreadable config ({e}); kept as {reserva}, using defaults")
            except OSError:
                _logger.warning(f"Unreadable config ({e}); using defaults")
            return config
        self._merge_configs(config, carregado)
        return config

    def _default_config(self) -> Dict[str, Any]:
        """Return default configuration.

        Only keys something reads. Docker image, network, timeouts, window and
        "advanced" entries used to be listed too; nothing used them (the
        values are constants in utils/constants.py). Old files that still
        carry them load fine; the keys are simply ignored.
        """
        return {
            "device": {"ip": "", "developer_mode": False},
            "certificates": {
                "use_default": True,  # Use built-in certificates from Docker container
                "author_cert_path": "",
                "distributor_cert_path": "",
            },
            # Tags pointing at a Jellyfin server, embedded into the TV build.
            # The URL stays here, in the user's config, and never in the
            # repository -- it is a private address and this repo is public.
            "customization": {
                "enabled": False,
                "server_url": "",
            },
            "logging": {"level": "INFO"},
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key.split(".")
        with self._lock:
            value = self._config
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            # A copy for containers: the caller must not edit the live config.
            return copy.deepcopy(value) if isinstance(value, (dict, list)) else value

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
        """Save atomically, readable by the owner only.

        Written to a temporary file and renamed over the old one: a crash
        mid-write used to leave a truncated file, which then loaded as
        defaults. 0600 because it holds the private server address and the
        certificate paths.
        """
        try:
            fd, tmp = tempfile.mkstemp(dir=self.config_dir, prefix=".config-", suffix=".json")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self._config, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.config_file)
            except BaseException:
                os.unlink(tmp)
                raise
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

