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
# feature jellyfin-web already knows how to show a menu for.
#
# Only two of AVPlay's three modes are offered. AUTO_ASPECT_RATIO is documented
# as following the video's DAR/PAR, but on a real set (LSP3, Tizen 6) it
# stretched exactly like FULL_SCREEN -- so LETTER_BOX, the one that actually
# kept the shape, is the default and is labelled as "the video's ratio".
_AVPLAY_METHODS = f"""    {_AVPLAY_MARKER}
    this._displayModes = {{
        letterbox: 'PLAYER_DISPLAY_MODE_LETTER_BOX',
        fill: 'PLAYER_DISPLAY_MODE_FULL_SCREEN'
    }};
    this._displayModeKey = 'jellybeam-avplay-display';
    this._applyDisplayMethod = function () {{
        var mode = this._displayModes[this.getAspectRatio()] || this._displayModes.letterbox;
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
        // jellyfin-web shows these names as they are; the player has no
        // access to its translations, so the set's language decides.
        var pt = /^pt/i.test(navigator.language || '');
        return [
            {{ name: pt ? 'Proporção do vídeo' : 'Video ratio', id: 'letterbox' }},
            {{ name: pt ? 'Preencher a tela' : 'Fill the screen', id: 'fill' }}
        ];
    }};
    this.getAspectRatio = function () {{
        var saved = '';
        try {{ saved = localStorage.getItem(this._displayModeKey) || ''; }} catch (e) {{}}
        return this._displayModes[saved] ? saved : 'letterbox';
    }};
    this.setAspectRatio = function (value) {{
        if (!this._displayModes[value]) {{ return; }}
        try {{ localStorage.setItem(this._displayModeKey, value); }} catch (e) {{}}
        this._applyDisplayMethod();
    }};
    // Nothing in the stock app stops the set starting its screen saver during
    // a film. tizen.power does not exist on Samsung TVs (checked on a real
    // set); the TV API is AppCommon.setScreenSaver, public, since Tizen 2.3.
    this._keepScreenOn = function (on) {{
        try {{
            var st = webapis.appcommon.AppCommonScreenSaverState;
            webapis.appcommon.setScreenSaver(on ? st.SCREEN_SAVER_OFF : st.SCREEN_SAVER_ON);
        }} catch (e) {{
            console.warn('setScreenSaver failed', e);
        }}
    }};
    // AVPlay parses the subtitle file and hands each cue to onsubtitlechange;
    // it does not draw anything. The stock player only logs the text, so
    // subtitles never appear. This draws them, styled from the Jellyfin
    // "Subtitles" appearance settings the user already has a menu for.
    this._subtitleTimer = null;
    this._subtitleAppearance = function () {{
        var raw = null;
        try {{
            for (var i = 0; i < localStorage.length; i++) {{
                var k = localStorage.key(i);
                if (k && k.indexOf('subtitleappearance') !== -1) {{ raw = localStorage.getItem(k); }}
            }}
            return raw ? JSON.parse(raw) : {{}};
        }} catch (e) {{ return {{}}; }}
    }};
    this._subtitleEl = function () {{
        var el = document.getElementById('jellybeam-subtitles');
        if (!el) {{
            el = document.createElement('div');
            el.id = 'jellybeam-subtitles';
            el.style.cssText = 'position:fixed;left:5%;right:5%;text-align:center;' +
                'z-index:100000;pointer-events:none;line-height:1.35;display:none;';
            document.body.appendChild(el);
        }}
        var a = this._subtitleAppearance();
        var sizes = {{ smaller: 0.8, small: 0.9, medium: 1, large: 1.2, larger: 1.5, extralarge: 1.8 }};
        el.style.fontSize = ((sizes[a.textSize] || 1) * 4.3) + 'vh';
        var fonts = {{
            typewriter: '"Courier New", monospace', print: 'Georgia, serif',
            console: 'Consolas, "Lucida Console", monospace', cursive: '"Brush Script MT", cursive',
            casual: '"Comic Sans MS", cursive', smallcaps: 'inherit'
        }};
        el.style.fontFamily = fonts[a.font] || 'inherit';
        el.style.fontVariant = a.font === 'smallcaps' ? 'small-caps' : 'normal';
        el.style.fontWeight = a.textWeight === 'bold' ? 'bold' : 'normal';
        el.style.color = a.textColor || '#ffffff';
        var shadows = {{
            none: 'none', raised: '#000 -1px -1px 0, #fff 1px 1px 0',
            depressed: '#fff -1px -1px 0, #000 1px 1px 0',
            uniform: '#000 -2px -2px 0, #000 2px -2px 0, #000 -2px 2px 0, #000 2px 2px 0'
        }};
        el.style.textShadow = shadows[a.dropShadow] || '#000 0 0 7px, #000 0 0 7px';
        var pos = parseInt(a.verticalPosition, 10); if (isNaN(pos)) {{ pos = -3; }}
        el.style.top = ''; el.style.bottom = '';
        if (pos < 0) {{ el.style.bottom = (-pos * 2.6) + 'vh'; }} else {{ el.style.top = (pos * 2.6 + 2) + 'vh'; }}
        el.setAttribute('data-bg', a.textBackground || 'transparent');
        return el;
    }};
    this._showSubtitle = function (text, duration) {{
        var el = this._subtitleEl();
        var safe = String(text || '')
            .replace(/\\r?\\n/g, '<br>')
            .replace(/<(?!\\/?(i|b|u|br)\\b)[^>]*>/gi, '');
        el.innerHTML = safe.trim() ? '<span style="background:' + el.getAttribute('data-bg') +
            ';padding:0 .3em;border-radius:.15em;box-decoration-break:clone;">' + safe + '</span>' : '';
        el.style.display = safe.trim() ? 'block' : 'none';
        if (this._subtitleTimer) {{ clearTimeout(this._subtitleTimer); }}
        var ms = parseInt(duration, 10);
        if (ms > 0) {{ this._subtitleTimer = setTimeout(function () {{ el.style.display = 'none'; }}, ms + 150); }}
    }};
    this._hideSubtitle = function () {{
        if (this._subtitleTimer) {{ clearTimeout(this._subtitleTimer); }}
        var el = document.getElementById('jellybeam-subtitles');
        if (el) {{ el.style.display = 'none'; el.innerHTML = ''; }}
    }};
    // External subtitles. The stock player hands the file to tizen.download
    // and then to setExternalSubtitlePath. Seen on a real set: the download
    // manager stalls on the server's chunked reply (158 bytes received,
    // total reported as 0, never completes), so no cue ever arrives. The
    // page can fetch the same URL itself -- it already talks to the server
    // for everything else -- so the .vtt is fetched, parsed here, and shown
    // against the player clock. No AVPlay text track involved.
    this._vttCues = null;
    this._vttTimer = null;
    this._vttOffset = 0;
    this._vttLast = null;
    this._parseVtt = function (text) {{
        var cues = [];
        var ts = /(?:(\\d+):)?(\\d{{1,2}}):(\\d{{2}})[.,](\\d{{1,3}})/g;
        var blocks = String(text || '').replace(/\\r/g, '').split(/\\n\\n+/);
        for (var i = 0; i < blocks.length; i++) {{
            var lines = blocks[i].split('\\n');
            var ti = -1;
            for (var j = 0; j < lines.length; j++) {{ if (lines[j].indexOf('-->') !== -1) {{ ti = j; break; }} }}
            if (ti < 0) {{ continue; }}
            var times = lines[ti].match(ts);
            if (!times || times.length < 2) {{ continue; }}
            var toMs = function (s) {{
                var m = /^(?:(\\d+):)?(\\d{{1,2}}):(\\d{{2}})[.,](\\d{{1,3}})$/.exec(s);
                return ((parseInt(m[1] || '0', 10) * 3600) + (parseInt(m[2], 10) * 60) + parseInt(m[3], 10)) * 1000 +
                    parseInt((m[4] + '00').slice(0, 3), 10);
            }};
            var body = lines.slice(ti + 1).join('\\n').trim();
            if (body) {{ cues.push({{ start: toMs(times[0]), end: toMs(times[1]), text: body }}); }}
        }}
        cues.sort(function (a, b) {{ return a.start - b.start; }});
        return cues;
    }};
    this._clearVtt = function () {{
        if (this._vttTimer) {{ clearInterval(this._vttTimer); this._vttTimer = null; }}
        this._vttCues = null; this._vttLast = null;
        this._hideSubtitle();
    }};
    this._tickVtt = function () {{
        var cues = this._vttCues;
        if (!cues) {{ return; }}
        var now;
        try {{ now = webapis.avplay.getCurrentTime() + (this._vttOffset || 0); }} catch (e) {{ return; }}
        var active = null;
        for (var i = 0; i < cues.length; i++) {{
            if (cues[i].start > now) {{ break; }}
            if (now < cues[i].end) {{ active = cues[i]; }}
        }}
        if (active !== this._vttLast) {{
            this._vttLast = active;
            if (active) {{ this._showSubtitle(active.text, 0); }} else {{ this._hideSubtitle(); }}
        }}
    }};
    this._loadExternalSubtitle = function (url) {{
        var self = this;
        self._clearVtt();
        var xhr = new XMLHttpRequest();
        xhr.open('GET', url, true);
        xhr.onload = function () {{
            if (xhr.status < 200 || xhr.status >= 300) {{
                console.warn('subtitle fetch failed', xhr.status); return;
            }}
            self._vttCues = self._parseVtt(xhr.responseText);
            console.debug('subtitle cues loaded: ' + self._vttCues.length);
            if (self._vttTimer) {{ clearInterval(self._vttTimer); }}
            self._vttTimer = setInterval(function () {{ self._tickVtt(); }}, 200);
        }};
        xhr.onerror = function () {{ console.warn('subtitle fetch error'); }};
        xhr.send();
    }};
    // The device profile the player sends decides what the server streams.
    // Seen on a 1080p set with a 4K HDR file: the stock profile lists a video
    // transcoding profile with an empty Protocol first, the server answers
    // with a progressive stream, and AVPlay fails to open it
    // (PLAYER_ERROR_CONNECTION_FAILED). HLS, further down the list, works.
    //
    // On a non-UHD panel the profile also declares 1920x1080 as the limit.
    // Measured on an LSP3 (FHD) by feeding AVPlay synthetic HEVC clips over
    // HTTP: 1080p SDR and 1080p HDR prepare fine; 4K SDR and 4K HDR both fail
    // with CONNECTION_FAILED. Resolution is the discriminator, not HDR, and
    // not the file -- matching Samsung's FHD-platform spec (HEVC/H.264 up to
    // FHD, level 4.1). With the limit declared, a server that cannot
    // transcode picks the item's 1080p version instead of failing on the 4K
    // one; a UHD panel gets no limit.
    this._tuneDeviceProfile = function (p) {{
        if (!p) {{ return p; }}
        p.TranscodingProfiles = (p.TranscodingProfiles || []).filter(function (t) {{
            return t.Type !== 'Video' || t.Protocol === 'hls';
        }});
        var uhd = false;
        try {{ uhd = !!webapis.productinfo.isUdPanelSupported(); }} catch (e) {{}}
        if (!uhd) {{
            p.CodecProfiles = (p.CodecProfiles || []).concat([{{
                Type: 'Video',
                Conditions: [
                    {{ Condition: 'LessThanEqual', Property: 'Width', Value: '1920', IsRequired: false }},
                    {{ Condition: 'LessThanEqual', Property: 'Height', Value: '1080', IsRequired: false }}
                ]
            }}]);
        }}
        return p;
    }};
    // getDeviceProfile is defined further down this constructor; wrap it once
    // the constructor has finished, which is before any playback starts.
    var jbSelf = this;
    setTimeout(function () {{
        var orig = jbSelf.getDeviceProfile;
        if (typeof orig !== 'function' || orig._jellybeam) {{ return; }}
        // The stock method returns a Promise; keep whichever shape it has.
        jbSelf.getDeviceProfile = function () {{
            var r = orig.apply(jbSelf, arguments);
            return (r && typeof r.then === 'function')
                ? r.then(function (p) {{ return jbSelf._tuneDeviceProfile(p); }})
                : jbSelf._tuneDeviceProfile(r);
        }};
        jbSelf.getDeviceProfile._jellybeam = true;
    }}, 0);

"""
_AVPLAY_RECT_FOLLOWUP = (
    "            self._applyDisplayMethod();\n"
    "            self._keepScreenOn(true);\n"
    "            self._clearVtt();\n"
)

# Optional hooks: each is (anchor, line to insert after it). Missing ones are
# skipped one by one with a warning, so an upstream edit to, say, pause()
# costs that hook and nothing else.
_AVPLAY_OPEN_ANCHOR = "            webapis.avplay.open(options.url);"
_AVPLAY_HOOKS = (
    # UHD sets only decode above 1080p when told so before prepare. It is NOT
    # harmless elsewhere: on a 1080p set (LSP3) playback stopped working
    # altogether with it on. So it is set only where the panel is UHD, which
    # productinfo can tell -- that privilege is already in the manifest.
    (
        _AVPLAY_OPEN_ANCHOR,
        "            try {\n"
        "                if (webapis.productinfo.isUdPanelSupported()) {\n"
        "                    webapis.avplay.setStreamingProperty('SET_MODE_4K', 'TRUE');\n"
        "                }\n"
        "            } catch (e) { console.warn('SET_MODE_4K skipped', e); }",
    ),
    (
        "        webapis.avplay.pause();\n        this.Events.trigger(this, 'pause');",
        "        this._keepScreenOn(false);",
    ),
    (
        "        webapis.avplay.play();\n        this.Events.trigger(this, 'unpause');",
        "        this._keepScreenOn(true);",
    ),
    (
        "            webapis.avplay.pause();\n"
        "            console.debug('stop 2', webapis.avplay.getState());",
        "            this._keepScreenOn(false);\n            this._clearVtt();",
    ),
    # Each cue AVPlay parses arrives here with its duration in ms. Seen on a
    # real set: the text arrives, and nothing else in the app draws it.
    (
        "                onsubtitlechange: function (duration, text, data3, data4) {\n"
        '                    console.debug("subtitleText: " + text);',
        "                    self._showSubtitle(text, duration);",
    ),
    # Subtitles switched off in the menu.
    (
        "            webapis.avplay.setSilentSubtitle(true);",
        "            this._clearVtt();",
    ),
    # External subtitle chosen: fetch and draw it here instead of handing it
    # to tizen.download (which stalls) and AVPlay.
    (
        "            if (track.DeliveryMethod === 'External') {",
        "                if (self._loadExternalSubtitle) {\n"
        "                    self._loadExternalSubtitle(window.ApiClient.getUrl(track.DeliveryUrl));\n"
        "                    return;\n"
        "                }",
    ),
    # The offset control in the OSD; the stock code has this call commented
    # out because AVPlay could not take it. Here it just shifts the clock.
    (
        "        var offsetValue = parseFloat(offset) * 1000;",
        "        this._vttOffset = offsetValue || 0; this._vttLast = null;",
    ),
)


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
    for ancora, insercao in _AVPLAY_HOOKS:
        if ancora in fonte:
            fonte = fonte.replace(ancora, ancora + "\n" + insercao, 1)
        else:
            _logger.warning("%s: hook anchor missing, skipped: %r", AVPLAY_FILE, ancora[:40])
    arquivo.write_text(fonte, encoding="utf-8")
    _logger.info("Patched %s with the aspect-ratio setting", AVPLAY_FILE)
    return True


# Scripts that ride inside the package rather than being fetched from the
# server: they depend on Tizen APIs (webapis.*) and mean nothing elsewhere.
TV_SCRIPTS = ("tv-fhd-versions.js",)
_TV_MARKER_START = "<!-- JellyBeam:tv -->"
_TV_MARKER_END = "<!-- /JellyBeam:tv -->"
_TV_BLOCK_PATTERN = re.compile(
    re.escape(_TV_MARKER_START) + r".*?" + re.escape(_TV_MARKER_END) + r"\n?", re.DOTALL
)


def install_tv_scripts(pkg_dir: PathLike, scripts: Sequence[str] = TV_SCRIPTS) -> List[str]:
    """Copy the TV-only scripts into www/ and reference them from index.html.

    Kept in its own marked block, separate from the server-resource block, so
    re-running either one never disturbs the other. Idempotent.
    """
    www = Path(pkg_dir) / "www"
    index = _index_path(www)
    for nome in scripts:
        origem = ASSETS_DIR / nome
        if not origem.is_file():
            raise CustomizationInjectionError(f"TV script not found: {origem}")
        (www / nome).write_bytes(origem.read_bytes())

    content = _TV_BLOCK_PATTERN.sub("", index.read_text(encoding="utf-8"))
    if "</body>" not in content:
        raise CustomizationInjectionError(f"no </body> found in {index}")
    tags = "".join(f'<script src="{html.escape(n, quote=True)}" defer></script>\n' for n in scripts)
    block = f"{_TV_MARKER_START}\n{tags}{_TV_MARKER_END}\n"
    index.write_text(content.replace("</body>", block + "</body>", 1), encoding="utf-8")
    _logger.info("Installed %d TV script(s) into %s", len(scripts), www)
    return list(scripts)


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
