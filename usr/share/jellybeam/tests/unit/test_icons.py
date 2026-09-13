"""Every icon the app names must exist in a stock Adwaita install.

A user's machine may carry a rich third-party icon theme; most do not. Four
legacy freedesktop names (emblem-ok, emblem-favorite, emblem-default,
emblem-documents) were dropped by Adwaita and resolved only because this
developer had an extra theme installed -- on anyone else's desktop they would
have shown a broken glyph.
"""

import pathlib
import re

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[2]


def nomes_de_icone():
    """Collect every *-symbolic name written anywhere in the source."""
    nomes = set()
    padrao = re.compile(r'["\']([a-z0-9-]+-symbolic)["\']')
    for arquivo in RAIZ.rglob("*.py"):
        if "tests" in arquivo.parts:
            continue
        nomes |= set(padrao.findall(arquivo.read_text(encoding="utf-8")))
    return sorted(nomes)


def test_icons_exist_in_stock_adwaita():
    Adw.init()
    display = Gdk.Display.get_default()
    if display is None:
        pytest.skip("no display available")

    theme = Gtk.IconTheme.get_for_display(display)
    # Ask Adwaita specifically: whatever theme this machine happens to use
    # would hide exactly the portability problem being guarded against.
    theme.set_theme_name("Adwaita")

    nomes = nomes_de_icone()
    assert nomes, "no icon names found; the scan is broken"

    ausentes = [n for n in nomes if not theme.has_icon(n)]
    assert not ausentes, f"missing from stock Adwaita: {', '.join(ausentes)}"
