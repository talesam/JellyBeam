# services/customization.py
"""
Injects pointers to server-hosted customizations into the Tizen build.

Why pointers and not the code itself: the TV app bundles jellyfin-web at build
time and never fetches index.html from the server, so anything the server
injects into its own index.html never reaches the TV. Embedding the actual
scripts in the .wgt would work, but then every tweak means rebuilding and
reinstalling on each device. Embedding only the <link>/<script> tags means the
TV picks up changes on the next app start.

The server address is deliberately NOT in this module. It lives in the user's
config (~/.config/jellybeam/), because this repository is public and a
third-party server address is private data.

Everything here is plain filesystem work on the host: the Docker workspace is
bind-mounted (/tmp/jellybeam -> /workspace), so the file the container builds
from is directly writable here. No docker exec, no shell quoting.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

from gi.repository import GLib

from utils.constants import (
    CUSTOMIZATION_ICON,
    CUSTOMIZATION_MARKER_END,
    CUSTOMIZATION_MARKER_START,
    CUSTOMIZATION_RESOURCES,
    JELLYFIN_ICON_FILE,
    JELLYFIN_INFO_ENDPOINT,
    TIMEOUT_HTTP_REQUEST,
)
from utils.exceptions import (
    CustomizationError,
    CustomizationInjectionError,
    CustomizationServerError,
    CustomizationURLError,
)

_logger = logging.getLogger(__name__)

# Matches a previously injected block, so re-running replaces it instead of
# stacking copies. DOTALL because the block spans several lines.
_BLOCK_PATTERN = re.compile(
    re.escape(CUSTOMIZATION_MARKER_START)
    + r".*?"
    + re.escape(CUSTOMIZATION_MARKER_END)
    + r"\n?",
    re.DOTALL,
)

_ACCEPTED_SCHEMES = ("http", "https")

PathLike = Union[str, Path]

# Files shipped with the app itself (usr/share/jellybeam/assets), as opposed
# to the ones fetched from the server at run time.
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


AVPLAY_FILE = "avplayVideoPlayer.js"
_AVPLAY_MARKER = "/* JellyBeam:aspect */"

# Anchors in jellyfin-tizen's AVPlay player. The first is where the player's
# feature methods start; the second is the call that sizes the video, made in
# the IDLE state, where setDisplayMethod may also be called.
_AVPLAY_METHODS_ANCHOR = "    this.canPlayMediaType = function (mediaType) {"
_AVPLAY_RECT_ANCHOR = (
    "            webapis.avplay.setDisplayRect("
    "elem.offsetLeft, elem.offsetTop, elem.offsetWidth, elem.offsetHeight);"
)

# The AVPlay display method is what decides whether the picture keeps its
# shape. The stock player never sets it, so the platform default applies and
# stretches every film to the full 16:9 panel. This adds the aspect-ratio
# feature jellyfin-web already knows how to show a menu for, mapped onto the
# three AVPlay modes, with "auto" -- the video's own DAR/PAR -- as default.
_AVPLAY_METHODS = f"""    {_AVPLAY_MARKER}
    this._displayModes = {{
        auto: 'PLAYER_DISPLAY_MODE_AUTO_ASPECT_RATIO',
        letterbox: 'PLAYER_DISPLAY_MODE_LETTER_BOX',
        fill: 'PLAYER_DISPLAY_MODE_FULL_SCREEN'
    }};
    this._displayModeKey = 'jellybeam-avplay-display';
    this._applyDisplayMethod = function () {{
        var mode = this._displayModes[this.getAspectRatio()] || this._displayModes.auto;
        try {{
            webapis.avplay.setDisplayMethod(mode);
        }} catch (e) {{
            console.warn('setDisplayMethod failed', e);
        }}
    }};
    this.supports = function (feature) {{
        return feature === 'SetAspectRatio';
    }};
    this.getSupportedAspectRatios = function () {{
        return [
            {{ name: 'Auto', id: 'auto' }},
            {{ name: 'Letterbox', id: 'letterbox' }},
            {{ name: 'Fill', id: 'fill' }}
        ];
    }};
    this.getAspectRatio = function () {{
        var saved = '';
        try {{ saved = localStorage.getItem(this._displayModeKey) || ''; }} catch (e) {{}}
        return this._displayModes[saved] ? saved : 'auto';
    }};
    this.setAspectRatio = function (value) {{
        if (!this._displayModes[value]) {{ return; }}
        try {{ localStorage.setItem(this._displayModeKey, value); }} catch (e) {{}}
        this._applyDisplayMethod();
    }};

"""
_AVPLAY_RECT_FOLLOWUP = "            self._applyDisplayMethod();\n"


def patch_avplay(pkg_dir: PathLike) -> bool:
    """Give the AVPlay player an aspect-ratio setting, defaulting to the video's.

    Returns False when there is nothing to patch: the standard build has no
    AVPlay player (its HTML5 video keeps the aspect ratio by itself), and an
    upstream rewrite that moves the anchors is logged rather than fatal --
    the install still goes through, just without this fix.
    """
    arquivo = Path(pkg_dir) / AVPLAY_FILE
    if not arquivo.is_file():
        _logger.info("No %s in the package; nothing to patch", AVPLAY_FILE)
        return False
    fonte = arquivo.read_text(encoding="utf-8")
    if _AVPLAY_MARKER in fonte:
        return True
    if _AVPLAY_METHODS_ANCHOR not in fonte or _AVPLAY_RECT_ANCHOR not in fonte:
        _logger.warning("%s changed upstream; aspect-ratio patch skipped", AVPLAY_FILE)
        return False
    fonte = fonte.replace(_AVPLAY_METHODS_ANCHOR, _AVPLAY_METHODS + _AVPLAY_METHODS_ANCHOR, 1)
    fonte = fonte.replace(
        _AVPLAY_RECT_ANCHOR, _AVPLAY_RECT_ANCHOR + "\n" + _AVPLAY_RECT_FOLLOWUP, 1
    )
    arquivo.write_text(fonte, encoding="utf-8")
    _logger.info("Patched %s with the aspect-ratio setting", AVPLAY_FILE)
    return True


def replace_icon(pkg_dir: PathLike, icon: Optional[PathLike] = None) -> Path:
    """Overwrite the package's launcher icon with the square one we ship.

    The OSA build's icon is the 1920x1080 wordmark, and the launcher tile on
    Samsung sets is square, so it comes out squashed with the text illegible.
    Only an existing icon.png is replaced: its absence means pkg_dir is not
    the unpacked .wgt, and creating one there would just hide that.
    """
    destino = Path(pkg_dir) / JELLYFIN_ICON_FILE
    if not destino.is_file():
        raise CustomizationInjectionError(f"no {JELLYFIN_ICON_FILE} in {pkg_dir}")
    origem = Path(icon) if icon else ASSETS_DIR / CUSTOMIZATION_ICON
    if not origem.is_file():
        raise CustomizationInjectionError(f"icon not found: {origem}")
    destino.write_bytes(origem.read_bytes())
    _logger.info("Replaced %s with %s", destino, origem.name)
    return destino


def has_scheme(url: str) -> bool:
    """Whether the user actually typed a scheme.

    Tested with '://' rather than urlparse: urlparse("localhost:8096") reports
    the scheme as "localhost", which would make a bare host-and-port look like
    it already had one.
    """
    return "://" in (url or "").strip()


def prefers_plain_http(url: str) -> bool:
    """Whether to try http before https for this host.

    A LAN box usually speaks plain http, and attempting TLS against it stalls
    until the timeout. A public domain is the opposite. Guessing the likely one
    first only affects ordering -- both are still tried.
    """
    host = urlparse(_with_scheme(url, "http")).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return True
    if "." not in host:  # a bare machine name on the local network
        return True
    if re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", host):
        return True
    return False


def _with_scheme(url: str, scheme: str) -> str:
    url = (url or "").strip()
    return url if has_scheme(url) else f"{scheme}://{url}"


def normalize_url(url: str, default_scheme: str = "https") -> str:
    """Validate the server URL and strip its trailing slash.

    A missing scheme is filled in rather than rejected: typing just the host is
    the common case, and resolve_server_url() works out which scheme actually
    answers. Anything other than http/https is still an error.

    Raises:
        CustomizationURLError: empty, malformed, or not http/https.
    """
    url = (url or "").strip()
    if not url:
        raise CustomizationURLError("", "server URL is empty")

    url = _with_scheme(url, default_scheme)

    parts = urlparse(url)
    if parts.scheme not in _ACCEPTED_SCHEMES:
        raise CustomizationURLError(
            url, f"scheme must be one of {', '.join(_ACCEPTED_SCHEMES)}"
        )
    if not parts.netloc:
        raise CustomizationURLError(url, "missing host")

    # A URL carrying quotes or angle brackets would break out of the HTML
    # attribute it gets written into. It is escaped on the way in anyway, but a
    # URL like this is a mistake worth reporting rather than silently mangling.
    if any(c in url for c in "\"'<>"):
        raise CustomizationURLError(url, "contains characters invalid in a URL")

    return url.rstrip("/")


def _resource_tag(base_url: str, resource: str) -> str:
    """Build the <link> or <script> tag for one resource path."""
    path = resource.lstrip("/")
    url = html.escape(f"{base_url}/{path}", quote=True)

    if path.endswith(".css"):
        return f'<link rel="stylesheet" href="{url}">'
    if path.endswith(".js"):
        # defer so the tag does not block parsing. Waiting for ApiClient to
        # exist is each script's own responsibility -- defer does not cover it.
        return f'<script src="{url}" defer></script>'

    raise CustomizationInjectionError(
        f"unsupported resource type: {resource} (expected .css or .js)"
    )


def build_block(base_url: str, resources: Sequence[str]) -> str:
    """Assemble the full marked block that gets inserted into index.html."""
    lines = [CUSTOMIZATION_MARKER_START]
    lines += [_resource_tag(base_url, r) for r in resources]
    lines.append(CUSTOMIZATION_MARKER_END)
    return "\n".join(lines) + "\n"


def _index_path(www_dir: PathLike) -> Path:
    index = Path(www_dir) / "index.html"
    if not index.is_file():
        raise CustomizationInjectionError(
            f"index.html not found at {index}. The jellyfin-tizen clone may "
            "not have finished, or its layout changed."
        )
    return index


def inject(
    www_dir: PathLike,
    base_url: str,
    resources: Optional[Sequence[str]] = None,
) -> List[str]:
    """Insert the customization tags into www/index.html, idempotently.

    Any block from a previous run is removed first, so building twice over the
    same workspace does not stack duplicates.

    Args:
        www_dir: the jellyfin-tizen www/ directory (host side of the mount).
        base_url: the Jellyfin server root, e.g. https://example.org
        resources: paths relative to the server root; defaults to
            CUSTOMIZATION_RESOURCES.

    Returns:
        The resource paths that were injected.

    Raises:
        CustomizationURLError: the URL is unusable.
        CustomizationInjectionError: index.html is missing or has no </body>.
    """
    resources = list(resources if resources is not None else CUSTOMIZATION_RESOURCES)
    if not resources:
        raise CustomizationInjectionError("resource list is empty")

    base_url = normalize_url(base_url)
    index = _index_path(www_dir)

    content = index.read_text(encoding="utf-8")
    content = _BLOCK_PATTERN.sub("", content)

    if "</body>" not in content:
        raise CustomizationInjectionError(
            f"no </body> found in {index}; refusing to guess where to insert"
        )

    block = build_block(base_url, resources)
    content = content.replace("</body>", block + "</body>", 1)
    index.write_text(content, encoding="utf-8")

    # The URL is user data and this log may be attached to a bug report, so
    # record how many resources went in, not where they point.
    _logger.info("Injected %d customization resource(s) into %s", len(resources), index)
    return resources


def remove(www_dir: PathLike) -> bool:
    """Strip a previously injected block. Returns True if one was present."""
    index = _index_path(www_dir)
    content = index.read_text(encoding="utf-8")
    stripped = _BLOCK_PATTERN.sub("", content)

    if stripped == content:
        return False

    index.write_text(stripped, encoding="utf-8")
    _logger.info("Removed customization block from %s", index)
    return True


def probe_server(base_url: str, timeout: int = TIMEOUT_HTTP_REQUEST) -> str:
    """Ask the Jellyfin server who it is, to validate the configured URL.

    /System/Info/Public needs no authentication, which is what makes it usable
    as a reachability check.

    Returns:
        The server name it reports, or its host when the name is blank.

    Raises:
        CustomizationURLError: the URL itself is unusable.
        CustomizationServerError: unreachable, or not a Jellyfin server.
    """
    base_url = normalize_url(base_url)
    url = f"{base_url}{JELLYFIN_INFO_ENDPOINT}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise CustomizationServerError(f"server answered HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise CustomizationServerError(f"could not connect: {e.reason}") from e
    except (TimeoutError, OSError) as e:
        raise CustomizationServerError(f"could not connect: {e}") from e
    except json.JSONDecodeError as e:
        raise CustomizationServerError("reply was not JSON") from e

    # A reachable web server that is not Jellyfin also returns 200 for many
    # paths, so check the payload actually looks like Jellyfin.
    if not isinstance(payload, dict) or "Version" not in payload:
        raise CustomizationServerError("this does not look like a Jellyfin server")

    return payload.get("ServerName") or urlparse(base_url).netloc


def probe_server_async(
    base_url: str,
    callback: Callable[[bool, str], None],
    timeout: int = TIMEOUT_HTTP_REQUEST,
) -> None:
    """Run probe_server off the main thread; callback lands back on it."""

    def run() -> None:
        try:
            name = probe_server(base_url, timeout)
            GLib.idle_add(callback, True, name)
        except CustomizationError as e:
            GLib.idle_add(callback, False, str(e))

    threading.Thread(target=run, daemon=True).start()


def resolve_server_url(
    url: str, timeout: int = TIMEOUT_HTTP_REQUEST
) -> Tuple[str, str]:
    """Work out the full URL of a server the user may have typed bare.

    When no scheme was given, both are tried and the one that answers wins.
    Actually asking beats assuming: the scheme is baked into the package the TV
    loads, so guessing wrong here fails silently on the TV, far from the cause.

    Returns:
        (resolved_url, server_name)

    Raises:
        CustomizationURLError: the address is unusable whatever the scheme.
        CustomizationServerError: no scheme produced a Jellyfin server.
    """
    if has_scheme(url):
        candidates = [normalize_url(url)]
    else:
        first = "http" if prefers_plain_http(url) else "https"
        second = "https" if first == "http" else "http"
        candidates = [
            normalize_url(url, default_scheme=first),
            normalize_url(url, default_scheme=second),
        ]

    last_error: Optional[CustomizationServerError] = None
    for candidate in candidates:
        try:
            return candidate, probe_server(candidate, timeout)
        except CustomizationServerError as e:
            last_error = e

    raise last_error or CustomizationServerError("no scheme answered")


def resolve_server_url_async(
    url: str,
    callback: Callable[[bool, str, str], None],
    timeout: int = TIMEOUT_HTTP_REQUEST,
) -> None:
    """Run resolve_server_url off the main thread.

    The callback gets (ok, resolved_url, server_name) on success, and
    (False, "", reason) on failure.
    """

    def run() -> None:
        try:
            resolved, name = resolve_server_url(url, timeout)
            GLib.idle_add(callback, True, resolved, name)
        except CustomizationError as e:
            GLib.idle_add(callback, False, "", str(e))

    threading.Thread(target=run, daemon=True).start()


def is_injected(www_dir: PathLike) -> bool:
    """Whether index.html currently carries an injected block."""
    try:
        content = _index_path(www_dir).read_text(encoding="utf-8")
    except CustomizationInjectionError:
        return False
    return bool(_BLOCK_PATTERN.search(content))


__all__ = [
    "build_block",
    "has_scheme",
    "inject",
    "is_injected",
    "normalize_url",
    "prefers_plain_http",
    "probe_server",
    "probe_server_async",
    "remove",
    "resolve_server_url",
    "resolve_server_url_async",
]
