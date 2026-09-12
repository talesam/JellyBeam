"""Tests for services/customization.py."""

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from services import customization
from utils.constants import (
    CUSTOMIZATION_MARKER_END,
    CUSTOMIZATION_MARKER_START,
    CUSTOMIZATION_RESOURCES,
)
from utils.exceptions import (
    CustomizationInjectionError,
    CustomizationServerError,
    CustomizationURLError,
)

INDEX_HTML = """<!DOCTYPE html>
<html>
<head><title>Jellyfin</title></head>
<body>
<div id="reactRoot"></div>
</body>
</html>
"""

URL = "https://example.org"


@pytest.fixture
def www_dir(tmp_path):
    """A www/ directory holding a realistic index.html."""
    d = tmp_path / "www"
    d.mkdir()
    (d / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    return d


def read_index(www_dir):
    return (www_dir / "index.html").read_text(encoding="utf-8")


class TestNormalizeUrl:
    def test_strips_trailing_slash(self):
        assert customization.normalize_url("https://example.org/") == (
            "https://example.org"
        )

    def test_keeps_path_and_port(self):
        assert customization.normalize_url("http://10.0.0.5:8096/jf") == (
            "http://10.0.0.5:8096/jf"
        )

    def test_fills_in_a_missing_scheme(self):
        # Typing just the host is the common case; resolve_server_url works out
        # which scheme actually answers.
        assert customization.normalize_url("example.org") == "https://example.org"
        assert customization.normalize_url("example.org", "http") == (
            "http://example.org"
        )

    def test_host_with_port_is_not_mistaken_for_a_scheme(self):
        # urlparse("localhost:8096") reports "localhost" as the scheme.
        assert customization.normalize_url("localhost:8096", "http") == (
            "http://localhost:8096"
        )

    def test_strips_surrounding_whitespace(self):
        assert customization.normalize_url("  https://example.org  ") == (
            "https://example.org"
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "ftp://example.org",  # wrong scheme
            "https://",  # no host
            'https://a"onerror=x',  # would break out of the attribute
            "https://a<script>",
        ],
    )
    def test_rejects_unusable_urls(self, bad):
        with pytest.raises(CustomizationURLError):
            customization.normalize_url(bad)


class TestBuildBlock:
    def test_css_becomes_link_and_js_becomes_deferred_script(self):
        block = customization.build_block(URL, ["a/x.css", "b/y.js"])
        assert '<link rel="stylesheet" href="https://example.org/a/x.css">' in block
        assert '<script src="https://example.org/b/y.js" defer></script>' in block

    def test_is_wrapped_in_markers(self):
        block = customization.build_block(URL, ["a.js"])
        assert block.startswith(CUSTOMIZATION_MARKER_START)
        assert CUSTOMIZATION_MARKER_END in block

    def test_leading_slash_does_not_double_up(self):
        block = customization.build_block(URL, ["/web/a.js"])
        assert "https://example.org/web/a.js" in block
        assert "example.org//web" not in block

    def test_unknown_extension_is_rejected(self):
        with pytest.raises(CustomizationInjectionError):
            customization.build_block(URL, ["a/logo.png"])


class TestInject:
    def test_inserts_before_closing_body(self, www_dir):
        customization.inject(www_dir, URL)
        content = read_index(www_dir)
        assert content.index(CUSTOMIZATION_MARKER_START) < content.index("</body>")

    def test_injects_every_default_resource(self, www_dir):
        injected = customization.inject(www_dir, URL)
        assert injected == list(CUSTOMIZATION_RESOURCES)
        content = read_index(www_dir)
        for resource in CUSTOMIZATION_RESOURCES:
            assert f"{URL}/{resource}" in content

    def test_running_twice_does_not_stack_blocks(self, www_dir):
        customization.inject(www_dir, URL)
        customization.inject(www_dir, URL)
        content = read_index(www_dir)
        assert content.count(CUSTOMIZATION_MARKER_START) == 1
        assert content.count(CUSTOMIZATION_MARKER_END) == 1

    def test_reinjecting_with_a_new_url_drops_the_old_one(self, www_dir):
        customization.inject(www_dir, "https://old.example")
        customization.inject(www_dir, "https://new.example")
        content = read_index(www_dir)
        assert "old.example" not in content
        assert "new.example" in content

    def test_preserves_the_original_markup(self, www_dir):
        customization.inject(www_dir, URL)
        content = read_index(www_dir)
        assert '<div id="reactRoot"></div>' in content
        assert "<title>Jellyfin</title>" in content

    def test_missing_index_is_reported(self, tmp_path):
        with pytest.raises(CustomizationInjectionError):
            customization.inject(tmp_path, URL)

    def test_missing_body_is_reported(self, www_dir):
        (www_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        with pytest.raises(CustomizationInjectionError):
            customization.inject(www_dir, URL)

    def test_bad_url_is_reported_before_touching_the_file(self, www_dir):
        before = read_index(www_dir)
        with pytest.raises(CustomizationURLError):
            customization.inject(www_dir, "ftp://example.org")
        assert read_index(www_dir) == before

    def test_empty_resource_list_is_rejected(self, www_dir):
        with pytest.raises(CustomizationInjectionError):
            customization.inject(www_dir, URL, resources=[])


class TestRemove:
    def test_restores_the_original_file(self, www_dir):
        original = read_index(www_dir)
        customization.inject(www_dir, URL)
        assert customization.remove(www_dir) is True
        assert read_index(www_dir) == original

    def test_returns_false_when_nothing_was_injected(self, www_dir):
        assert customization.remove(www_dir) is False

    def test_is_safe_to_call_twice(self, www_dir):
        customization.inject(www_dir, URL)
        assert customization.remove(www_dir) is True
        assert customization.remove(www_dir) is False


class FakeResponse(io.BytesIO):
    """Minimal stand-in for what urlopen returns in a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(payload):
    return lambda url, timeout=None: FakeResponse(json.dumps(payload).encode("utf-8"))


class TestProbeServer:
    def test_returns_the_reported_server_name(self):
        with patch(
            "urllib.request.urlopen",
            fake_urlopen({"ServerName": "Contos", "Version": "12.0.0"}),
        ):
            assert customization.probe_server(URL) == "Contos"

    def test_falls_back_to_the_host_when_name_is_blank(self):
        with patch(
            "urllib.request.urlopen",
            fake_urlopen({"ServerName": "", "Version": "12.0.0"}),
        ):
            assert customization.probe_server("https://tv.example.org") == (
                "tv.example.org"
            )

    def test_queries_the_public_info_endpoint(self):
        seen = {}

        def spy(url, timeout=None):
            seen["url"] = url
            return FakeResponse(json.dumps({"Version": "12.0.0"}).encode())

        with patch("urllib.request.urlopen", spy):
            customization.probe_server("https://example.org/")
        assert seen["url"] == "https://example.org/System/Info/Public"

    def test_rejects_a_reachable_server_that_is_not_jellyfin(self):
        # A random web server answers 200 for plenty of paths; without this
        # check the user would get a green light and a broken TV build.
        with patch("urllib.request.urlopen", fake_urlopen({"nginx": "hello"})):
            with pytest.raises(CustomizationServerError):
                customization.probe_server(URL)

    def test_reports_a_non_json_reply(self):
        with patch(
            "urllib.request.urlopen",
            lambda url, timeout=None: FakeResponse(b"<html>nope</html>"),
        ):
            with pytest.raises(CustomizationServerError):
                customization.probe_server(URL)

    def test_reports_an_http_error(self):
        def raise_http(url, timeout=None):
            raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)

        with patch("urllib.request.urlopen", raise_http):
            with pytest.raises(CustomizationServerError):
                customization.probe_server(URL)

    def test_reports_a_connection_failure(self):
        def raise_url(url, timeout=None):
            raise urllib.error.URLError("no route to host")

        with patch("urllib.request.urlopen", raise_url):
            with pytest.raises(CustomizationServerError):
                customization.probe_server(URL)

    def test_validates_the_url_before_any_request(self):
        def explode(url, timeout=None):
            raise AssertionError("should not have been called")

        with patch("urllib.request.urlopen", explode):
            with pytest.raises(CustomizationURLError):
                customization.probe_server("ftp://example.org")


class TestIsInjected:
    def test_reflects_the_current_state(self, www_dir):
        assert customization.is_injected(www_dir) is False
        customization.inject(www_dir, URL)
        assert customization.is_injected(www_dir) is True
        customization.remove(www_dir)
        assert customization.is_injected(www_dir) is False

    def test_missing_index_counts_as_not_injected(self, tmp_path):
        assert customization.is_injected(tmp_path) is False


class TestSchemeHeuristics:
    @pytest.mark.parametrize(
        "host",
        ["localhost:8096", "192.168.1.5", "10.0.0.2", "172.16.0.9", "tv.local", "nas"],
    )
    def test_local_hosts_try_plain_http_first(self, host):
        assert customization.prefers_plain_http(host) is True

    @pytest.mark.parametrize("host", ["example.org", "jf.example.co.uk", "8.8.8.8"])
    def test_public_hosts_try_https_first(self, host):
        assert customization.prefers_plain_http(host) is False

    def test_detects_a_scheme_the_user_typed(self):
        assert customization.has_scheme("https://x.org") is True
        assert customization.has_scheme("x.org") is False
        assert customization.has_scheme("localhost:8096") is False


class TestResolveServerUrl:
    def test_falls_back_to_the_other_scheme(self):
        seen = []

        def only_http(url, timeout=None):
            seen.append(url)
            if url.startswith("https://"):
                raise urllib.error.URLError("no tls here")
            return FakeResponse(json.dumps({"Version": "12"}).encode())

        with patch("urllib.request.urlopen", only_http):
            resolved, _ = customization.resolve_server_url("example.org")
        assert resolved == "http://example.org"
        assert len(seen) == 2  # https first for a public host, then http

    def test_keeps_a_scheme_the_user_typed(self):
        seen = []

        def spy(url, timeout=None):
            seen.append(url)
            raise urllib.error.URLError("nope")

        with patch("urllib.request.urlopen", spy):
            with pytest.raises(CustomizationServerError):
                customization.resolve_server_url("http://example.org")
        assert seen == ["http://example.org/System/Info/Public"]

    def test_returns_the_resolved_url_and_name(self):
        with patch(
            "urllib.request.urlopen",
            fake_urlopen({"ServerName": "Contos", "Version": "12"}),
        ):
            assert customization.resolve_server_url("example.org") == (
                "https://example.org",
                "Contos",
            )
