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
import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence, Union
from urllib.parse import urlparse

from utils.constants import (
    CUSTOMIZATION_MARKER_END,
    CUSTOMIZATION_MARKER_START,
    CUSTOMIZATION_RESOURCES,
)
from utils.exceptions import CustomizationInjectionError, CustomizationURLError

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


def normalize_url(url: str) -> str:
    """Validate the server URL and strip its trailing slash.

    Raises:
        CustomizationURLError: empty, malformed, or not http/https.
    """
    url = (url or "").strip()
    if not url:
        raise CustomizationURLError("", "server URL is empty")

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


def is_injected(www_dir: PathLike) -> bool:
    """Whether index.html currently carries an injected block."""
    try:
        content = _index_path(www_dir).read_text(encoding="utf-8")
    except CustomizationInjectionError:
        return False
    return bool(_BLOCK_PATTERN.search(content))


__all__ = [
    "build_block",
    "inject",
    "is_injected",
    "normalize_url",
    "remove",
]
