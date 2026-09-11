# utils/constants.py
"""
Centralized constants for the JellyBeam application.

This module contains all hardcoded values that were previously scattered
across the codebase. Centralizing them here makes the application more
maintainable and configurable.
"""

# Network Constants
NETWORK_DNS_SERVER = "8.8.8.8"
NETWORK_DNS_PORT = 80
SAMSUNG_API_PORT = 8001
SAMSUNG_API_ENDPOINT = "/api/v2/"
SDB_PORT = 26101
NETWORK_IP_RANGE_START = 1
NETWORK_IP_RANGE_END = 254  # Skip .0 (network) and .255 (broadcast)

# Timeout Constants (in seconds)
TIMEOUT_DOCKER_VERSION = 5
TIMEOUT_DOCKER_INFO = 5
TIMEOUT_DOCKER_START = 30
TIMEOUT_DOCKER_STOP = 30
TIMEOUT_DOCKER_PULL = 300
TIMEOUT_DOCKER_EXEC_SHORT = 60
TIMEOUT_DOCKER_EXEC_MEDIUM = 120
TIMEOUT_DOCKER_EXEC_LONG = 300
TIMEOUT_DOCKER_SDK_SETUP = 600
TIMEOUT_DOCKER_INSTALL = 300
TIMEOUT_SDB_CONNECT = 10
TIMEOUT_SDB_DEVICES = 5
TIMEOUT_SDB_DISCONNECT = 10
TIMEOUT_PING = 2
TIMEOUT_SOCKET = 1
TIMEOUT_HTTP_REQUEST = 3
TIMEOUT_CERTIFICATE_VALIDATION = 30
TIMEOUT_NETWORK_SCAN = 30
TIMEOUT_UI_FEEDBACK = 2000  # milliseconds
TIMEOUT_STATUS_CHECK = 500  # milliseconds

# Docker Constants
DOCKER_CONTAINER_NAME = "jellybeam-builder"
DOCKER_IMAGE_NAME = "ghcr.io/georift/install-jellyfin-tizen"
DOCKER_IMAGE_TAG = "latest"
DOCKER_WORKSPACE_HOST = "/tmp/jellybeam"
DOCKER_WORKSPACE_CONTAINER = "/workspace"

# Tizen SDK Constants
TIZEN_SDK_VERSION = "4.6"
TIZEN_SDK_URL = f"http://download.tizen.org/sdk/Installer/tizen-studio_{TIZEN_SDK_VERSION}/web-cli_Tizen_Studio_{TIZEN_SDK_VERSION}_ubuntu-64.bin"
TIZEN_SDK_DIR = "tizen-studio"
TIZEN_TOOLS_PATH = "tizen-studio/tools/ide/bin/tizen"
TIZEN_SDK_BIN_NAME = "tizen-studio.bin"

# Jellyfin Constants
JELLYFIN_REPO_URL = "https://github.com/jellyfin/jellyfin-tizen.git"
JELLYFIN_REPO_DIR = "jellyfin-tizen"
JELLYFIN_APP_FILENAME = "jellyfin.wgt"
JELLYFIN_WWW_DIR = "www"

# Server Customization Constants
#
# The TV app bundles jellyfin-web at build time, so JavaScript the server
# injects into its own index.html never reaches it. We instead embed tags
# pointing back at the server, resolved on every app start.
#
# Only relative paths live here. The server address is user data and belongs
# in ~/.config/jellybeam/ -- never in this repository, which is public.
JELLYFIN_INFO_ENDPOINT = "/System/Info/Public"
CUSTOMIZATION_MARKER_START = "<!-- JellyBeam:start -->"
CUSTOMIZATION_MARKER_END = "<!-- JellyBeam:end -->"
CUSTOMIZATION_RESOURCES = (
    "MediaBarEnhanced/Resources/mediaBarEnhanced.css",
    "MediaBarEnhanced/Resources/mediaBarEnhanced.js",
    "web/cs-nav.js",
)

# Certificate Constants
CERT_FILE_EXTENSION = ".p12"
CERT_AUTHOR_FILENAME = "author.p12"
CERT_DISTRIBUTOR_FILENAME = "distributor.p12"
CERT_PASSWORD_FILE = ".password"
DEFAULT_PROFILE_NAME = "JellyBeam"
DEFAULT_DEVICE_ID = "DEVICE-001"

# Default Certificate Settings
# When True, uses built-in certificates from the Docker container
# No need for users to create certificates via Tizen Studio
USE_DEFAULT_CERTIFICATES = True

# UI Window Constants
WINDOW_DEFAULT_WIDTH = 800
WINDOW_DEFAULT_HEIGHT = 680
WINDOW_MIN_WIDTH = 700
WINDOW_MIN_HEIGHT = 600

# UI Layout Constants
CLAMP_MAX_SIZE = 800
CLAMP_TIGHTENING_THRESHOLD = 600
MARGIN_SMALL = 24
MARGIN_MEDIUM = 32
MARGIN_LARGE = 48

# Terminal/Console Constants
TERMINAL_HEIGHT = 300
TERMINAL_SCROLLBACK_LINES = 1000

# Application Metadata
APP_ID = "org.talesam.jellybeam"
APP_VERSION = "1.1.0"
APP_NAME = "JellyBeam"
APP_GITHUB_URL = "https://github.com/talesam/jellybeam"
APP_ISSUE_URL = "https://github.com/talesam/jellybeam/issues"
APP_COPYRIGHT = "© 2026 JellyBeam"

# Network Scanning Constants
SCAN_MAX_WORKERS = 30
SCAN_PORTS_DEFAULT = [8001, 8002, 8080, 9197, 55000, 7001, 26101]

# Samsung Device Indicators
SAMSUNG_DEVICE_INDICATORS = ["samsung", "tizen", "smarttv"]

# Docker Installation Commands by Distribution
DOCKER_INSTALL_COMMANDS = {
    "arch": [
        ["sudo", "pacman", "-S", "--noconfirm", "docker", "docker-compose"],
        ["sudo", "systemctl", "enable", "docker"],
        ["sudo", "usermod", "-aG", "docker", "$USER"],
    ],
    "debian": [
        ["sudo", "apt", "update"],
        ["sudo", "apt", "install", "-y", "docker.io", "docker-compose"],
        ["sudo", "systemctl", "enable", "docker"],
        ["sudo", "usermod", "-aG", "docker", "$USER"],
    ],
    "fedora": [
        ["sudo", "dnf", "install", "-y", "docker", "docker-compose"],
        ["sudo", "systemctl", "enable", "docker"],
        ["sudo", "usermod", "-aG", "docker", "$USER"],
    ],
}

# Docker Start Commands (fallback options)
DOCKER_START_COMMANDS = [
    ["sudo", "systemctl", "start", "docker"],
    ["sudo", "service", "docker", "start"],
    ["sudo", "/etc/init.d/docker", "start"],
]

# Configuration Paths
CONFIG_DIR_NAME = ".config/jellybeam"
LOG_DIR_NAME = ".local/share/jellybeam/logs"
LOG_FILE_PATTERN = "jellybeam_%Y%m%d.log"
CONFIG_FILE_NAME = "config.json"

# Logging Constants
LOG_MAX_AGE_DAYS = 30
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
