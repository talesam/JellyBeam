# utils/logger.py
import logging
from pathlib import Path
from datetime import datetime


class Logger:
    """Application logging manager."""

    def __init__(self):
        self.logger = logging.getLogger("jellybeam")
        self.log_dir = Path.home() / ".local" / "share" / "jellybeam" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._setup_logger()

    def _setup_logger(self):
        """Setup logger configuration."""
        # Skip if handlers already configured (prevents duplicates on re-instantiation)
        if self.logger.handlers:
            return

        self.logger.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # File handler
        log_file = self.log_dir / f"jellybeam_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # Add handlers
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def set_level(self, level):
        """Set logging level."""
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }

        if level in level_map:
            # Update console handler level
            for handler in self.logger.handlers:
                if isinstance(handler, logging.StreamHandler) and not isinstance(
                    handler, logging.FileHandler
                ):
                    handler.setLevel(level_map[level])
                    break

    def debug(self, message):
        """Log debug message."""
        self.logger.debug(message)

    def info(self, message):
        """Log info message."""
        self.logger.info(message)

    def warning(self, message):
        """Log warning message."""
        self.logger.warning(message)

    def error(self, message):
        """Log error message."""
        self.logger.error(message)

    def exception(self, message):
        """Log exception with traceback."""
        self.logger.exception(message)

    def get_log_files(self):
        """Get list of available log files."""
        log_files = []
        for file in self.log_dir.glob("jellybeam_*.log"):
            log_files.append(
                {
                    "name": file.name,
                    "path": str(file),
                    "size": file.stat().st_size,
                    "modified": datetime.fromtimestamp(file.stat().st_mtime),
                }
            )

        return sorted(log_files, key=lambda x: x["modified"], reverse=True)

    def clear_old_logs(self, days=30):
        """Clear log files older than specified days."""
        cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)

        for file in self.log_dir.glob("jellybeam_*.log"):
            if file.stat().st_mtime < cutoff_time:
                try:
                    file.unlink()
                    self.info(f"Removed old log file: {file.name}")
                except OSError as e:
                    self.error(f"Failed to remove log file {file.name}: {e}")
