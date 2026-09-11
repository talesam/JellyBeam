"""Tests for services/customization.py."""

import pytest

from services import customization
from utils.constants import (
    CUSTOMIZATION_MARKER_END,
    CUSTOMIZATION_MARKER_START,
    CUSTOMIZATION_RESOURCES,
)
from utils.exceptions import CustomizationInjectionError, CustomizationURLError

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

    def test_strips_surrounding_whitespace(self):
        assert customization.normalize_url("  https://example.org  ") == (
            "https://example.org"
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "example.org",  # no scheme
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
            customization.inject(www_dir, "not-a-url")
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


class TestIsInjected:
    def test_reflects_the_current_state(self, www_dir):
        assert customization.is_injected(www_dir) is False
        customization.inject(www_dir, URL)
        assert customization.is_injected(www_dir) is True
        customization.remove(www_dir)
        assert customization.is_injected(www_dir) is False

    def test_missing_index_counts_as_not_injected(self, tmp_path):
        assert customization.is_injected(tmp_path) is False
