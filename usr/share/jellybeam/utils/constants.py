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
# Where sdb lives inside the image, for commands run by hand there.
TIZEN_TOOLS_DIR = "/tizen-studio/tools"
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

# Which published variant to install.
#
# OSA carries a second video player built on AVPlay, Tizen's native media API.
# The standard build plays through the browser's <video>, whose codec support
# is narrower than the TV's own decoder, so the server ends up transcoding
# formats the hardware could have played directly. OSA also folds in the
# OblongIcon and SmartHub builds.
#
# Upstream calls the AVPlay support experimental, and it is: a second player
# means a second set of playback bugs. It fails at playback, never at install,
# and switching back is one reinstall away.
JELLYFIN_BUILD_DEFAULT = "Jellyfin-OSA"

# Pre-built Tizen packages. The Docker image installs these instead of
# compiling jellyfin-tizen, so customizing means unpacking one, editing it and
# signing it again -- see services/docker.py.
JELLYFIN_BUILDS_RELEASES = (
    "https://github.com/jeppevinkel/jellyfin-tizen-builds/releases"
)
# Signing profile shipped inside the image, along with its author certificate.
# It is what lets us re-sign without asking the user for a certificate.
TIZEN_SIGN_PROFILE = "dev"
CUSTOMIZATION_PKG_DIR = "pkg"
CUSTOMIZATION_MARKER_START = "<!-- JellyBeam:start -->"
CUSTOMIZATION_MARKER_END = "<!-- JellyBeam:end -->"
# Media Bar Enhanced used to be here as well, and was dropped: on a projector
# its carousel made the whole interface crawl. Anyone running it can add the
# two paths back:
#   MediaBarEnhanced/Resources/mediaBarEnhanced.css
#   MediaBarEnhanced/Resources/mediaBarEnhanced.js
# A resource the server does not have is not an error -- the tag just fails --
# but it costs a failed request at every app start, which is worth avoiding on
# TV hardware.
CUSTOMIZATION_RESOURCES = ("web/cs-nav.js",)
# The launcher tile on Samsung sets is square; the OSA build ships the wide
# 1920x1080 wordmark as its icon and it gets squashed. The customized build
# swaps in a square icon built on the official Jellyfin symbol (CC BY-SA 4.0).
JELLYFIN_ICON_FILE = "icon.png"
CUSTOMIZATION_ICON = "tv-icon.png"
# Version written into the customized package's config.xml (the upstream .wgt
# says 0.1.0 forever). Bump on EVERY change to what goes to the TV: middle
# number for a new feature, last number for a fix. It is what Jellyfin shows
# in the device list, and the only way to know which build a user has.
CUSTOMIZATION_APP_VERSION = "0.9.0"
# jellyfin-web's own logo files, replaced so the splash, the header and the
# login screen show our branding. Square files are matched by pixel size to a
# symbol of the same size; the wide banners (splash screen, header) get
# symbol + "Jellyfin" wordmark.
BRANDING_DIR = "branding"
BRANDING_BANNER = "banner.png"
BRANDING_PATTERNS = (
    "www/banner-light.*.png",
    "www/banner-dark.*.png",
    "www/icon-transparent.*.png",
    "www/notificationicon.*.png",
    "www/touchicon*.png",
    "www/favicons/touchicon*.png",
)

# From this Tizen version on, the TV verifies that the signing chain has not
# expired. The published package is signed with a certificate that lapsed in
# 2022, so these TVs refuse it and we sign our own instead.
TIZEN_STRICT_CERT_VERSION = 8
# Where the user's certificate is staged for the container to read.
DEVICE_CERT_DIR = "certs"

# Samsung certificate issuance.
#
# Not a published API: this is the flow Tizen Studio's Certificate Manager
# uses. The sign-in URL and the CA files are read out of the official Samsung
# Certificate Extension at run time instead of being written here -- the
# service id has already changed once in the wild, and the loopback address
# Samsung redirects to is one it registered, not one we may choose.
SAMSUNG_CERT_EXTENSION_INFO = (
    "https://download.tizen.org/sdk/tizenstudio/official/extension_info.xml"
)
SAMSUNG_CERT_EXTENSION_ZIP = (
    "https://download.tizen.org/sdk/extensions/"
    "tizen-certificate-extension_{version}.zip"
)
# The issuing host, as compiled into the Certificate Manager (CertConstant
# AUTHOR_URL / DISTRIBUTOR_URL). It is not dev.tizen.samsung.com, which is what
# blog posts name and which times out.
SAMSUNG_CERT_AUTHOR_API = "https://svdca.samsungqbe.com/apis/v3/authors"
SAMSUNG_CERT_DISTRIBUTOR_API = "https://svdca.samsungqbe.com/apis/v3/distributors"
# VD is Samsung's name for the TV platform; the watch and phone CAs in the
# same directory are for other devices and will not validate on a television.
SAMSUNG_CERT_CA_AUTHOR = "vd_tizen_dev_author_ca.cer"
SAMSUNG_CERT_CA_DISTRIBUTOR = "vd_tizen_dev_public2.crt"

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

# Docker Start Commands, in order of preference.
#
# No "sudo" here: these run through pkexec, which already gives root and,
# unlike sudo, asks for the password in a graphical dialog. With sudo the
# prompt went to a pipe, so nothing appeared on screen and the app simply
# hung -- a user hit exactly that.
DOCKER_START_COMMANDS = [
    ["systemctl", "start", "docker"],
    ["service", "docker", "start"],
    ["/etc/init.d/docker", "start"],
]

# pkexec's own exit codes, distinct from the command it ran.
PKEXEC_DISMISSED = 126
PKEXEC_NOT_AUTHORIZED = 127

# Configuration Paths
CONFIG_DIR_NAME = ".config/jellybeam"
LOG_DIR_NAME = ".local/share/jellybeam/logs"
LOG_FILE_PATTERN = "jellybeam_%Y%m%d.log"
CONFIG_FILE_NAME = "config.json"

# Logging Constants
LOG_MAX_AGE_DAYS = 30
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
