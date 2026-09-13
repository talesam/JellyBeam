"""The target-device subtitle is rebuilt, never appended to.

The version arrives asynchronously, well after the row was first filled in.
Appending it to whatever the widget already showed duplicated it on every
return to the page.
"""

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Vte", "3.91")
from gi.repository import Adw  # noqa: E402


class FakeRow:
    def __init__(self):
        self.subtitle = ""

    def set_subtitle(self, t):
        self.subtitle = t

    def get_subtitle(self):
        return self.subtitle


def render(page):
    from pages.install import InstallPage

    InstallPage._render_tv_subtitle(page)


class Page:
    """Just the two attributes _render_tv_subtitle reads."""

    def __init__(self, base="", note=""):
        self._tv_subtitle_base = base
        self._tv_version_note = note
        self.tv_info_row = FakeRow()


def test_version_is_not_duplicated_on_repeat_visits():
    Adw.init()
    page = Page("IP: 10.0.0.5 | UN49KU6300", "Tizen 6.5")
    for _ in range(4):
        render(page)
    assert page.tv_info_row.get_subtitle().count("Tizen") == 1


def test_subtitle_without_a_version_has_no_dangling_separator():
    Adw.init()
    page = Page("IP: 10.0.0.5", "")
    render(page)
    assert page.tv_info_row.get_subtitle() == "IP: 10.0.0.5"


def test_failed_read_is_shown_rather_than_swallowed():
    Adw.init()
    page = Page("IP: 10.0.0.5", "Tizen version unavailable")
    render(page)
    # Silence was the defect: the row looked as if the feature did not exist.
    assert "unavailable" in page.tv_info_row.get_subtitle()
