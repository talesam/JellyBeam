# utils/design.py
"""Shared visual pieces, so the pages look like one application.

Every page used to build its own headers and status markers inline, which is
why they had drifted apart. The builders here are the recurring elements of
the design: an icon badge, a page header with the step indicator, a status
pill and the footer signature.

Nothing here holds state or talks to services -- these are widgets only, safe
to call from any page.
"""

from __future__ import annotations

import logging

from typing import Optional, Sequence, Tuple

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from utils.constants import APP_NAME  # noqa: E402
from utils.i18n import _  # noqa: E402

_logger = logging.getLogger(__name__)

# The four steps of the wizard, in order. Pages pass their own index so the
# indicator cannot drift out of step with the actual navigation.
STEP_DEVICE = 0
STEP_CONNECT = 1
STEP_INSTALL = 2
STEP_COMPLETE = 3

# Diameter of the numbered circles, in pixels. Also referenced by the CSS
# below; keep the two in step.
STEP_DOT = 28

CSS = b"""
.jb-badge {
    background-color: alpha(currentColor, 0.10);
    border-radius: 12px;
    min-width: 40px;
    min-height: 40px;
}
.jb-badge-accent {
    background-color: alpha(@accent_bg_color, 0.18);
    color: @accent_bg_color;
}
.jb-badge-warning {
    background-color: alpha(@warning_bg_color, 0.18);
    color: @warning_bg_color;
}
.jb-badge-hero {
    border-radius: 18px;
    min-width: 64px;
    min-height: 64px;
}

.jb-hero-icon {
    -gtk-icon-size: 56px;
    color: @accent_bg_color;
}
.jb-hero-title {
    font-size: 26pt;
    font-weight: 800;
}
.jb-page-title {
    font-size: 19pt;
    font-weight: 800;
}

.jb-pill {
    border-radius: 999px;
    padding: 3px 12px;
    font-size: 0.85em;
    font-weight: 700;
}
.jb-pill-ok {
    background-color: alpha(@success_bg_color, 0.20);
    color: @success_color;
}
.jb-pill-idle {
    background-color: alpha(currentColor, 0.10);
}

.jb-step-num {
    border-radius: 999px;
    font-size: 0.8em;
    font-weight: 700;
    font-feature-settings: "tnum";
    background-color: alpha(currentColor, 0.10);
}
.jb-step-num-current {
    background-color: @accent_bg_color;
    color: @accent_fg_color;
}
.jb-step-num-done {
    background-color: alpha(@accent_bg_color, 0.30);
    color: @accent_bg_color;
}
.jb-step-line {
    background-color: alpha(currentColor, 0.20);
    min-height: 2px;
    min-width: 22px;
}
.jb-step-label {
    font-size: 0.75em;
}

.jb-feature-title {
    font-weight: 700;
}
.jb-footer {
    font-size: 0.8em;
}
"""


def load_css() -> None:
    """Install the stylesheet once, for the whole application."""
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


FALLBACK_ICON = "application-x-executable-symbolic"


def resolve_icon(icon_name: str) -> str:
    """Return icon_name if the theme really has it, else a safe stand-in.

    Icon names are not portable between themes: two of the names used here
    were missing or not truly symbolic on this desktop, and produced a broken
    glyph and an empty badge. A name that is not there should degrade to
    something visible rather than to a hole in the layout.
    """
    display = Gdk.Display.get_default()
    if display is None:
        return icon_name
    theme = Gtk.IconTheme.get_for_display(display)
    if theme.has_icon(icon_name):
        return icon_name
    _logger.warning("Icon %r missing from the theme; using a stand-in", icon_name)
    return FALLBACK_ICON


def icon_badge(icon_name: str, tone: str = "", hero: bool = False) -> Gtk.Image:
    """An icon sitting on a rounded, tinted square.

    Args:
        tone: "accent", "warning", or "" for the neutral grey.
        hero: the larger size used by page headers.
    """
    image = Gtk.Image.new_from_icon_name(resolve_icon(icon_name))
    image.set_valign(Gtk.Align.CENTER)
    image.add_css_class("jb-badge")
    if tone:
        image.add_css_class(f"jb-badge-{tone}")
    if hero:
        image.add_css_class("jb-badge-hero")
        image.set_pixel_size(30)
    else:
        image.set_pixel_size(18)
    return image


def status_pill(text: str, ok: bool = False) -> Gtk.Box:
    """A small rounded label for a state, green when things are fine."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    box.set_valign(Gtk.Align.CENTER)
    box.add_css_class("jb-pill")
    box.add_css_class("jb-pill-ok" if ok else "jb-pill-idle")
    if ok:
        box.append(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
    label = Gtk.Label(label=text)
    box.append(label)
    return box


def step_indicator(current: int) -> Gtk.Box:
    """The numbered progress across the wizard, 1 to 4."""
    steps = [_("Setup Device"), _("Connect"), _("Install"), _("Complete")]

    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    row.set_valign(Gtk.Align.CENTER)

    for index, name in enumerate(steps):
        if index:
            line = Gtk.Box()
            line.add_css_class("jb-step-line")
            line.set_valign(Gtk.Align.CENTER)
            line.set_margin_bottom(16)
            row.append(line)

        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cell.set_halign(Gtk.Align.CENTER)

        number = Gtk.Label(label=str(index + 1))
        number.add_css_class("jb-step-num")
        # Fixed geometry, not just a CSS minimum: with min-width alone the
        # circles came out at slightly different sizes, because each label
        # still sized itself to its own glyph and to whatever the cell below
        # it was doing. A request pins all four to the same box.
        number.set_size_request(STEP_DOT, STEP_DOT)
        number.set_halign(Gtk.Align.CENTER)
        number.set_valign(Gtk.Align.CENTER)
        if index == current:
            number.add_css_class("jb-step-num-current")
        elif index < current:
            number.add_css_class("jb-step-num-done")
        cell.append(number)

        label = Gtk.Label(label=name)
        label.add_css_class("jb-step-label")
        label.add_css_class("dim-label")
        # "Setup Device" already wraps to two lines in English, and in most
        # other languages it is longer still. Let it wrap rather than asking
        # translators for abbreviations that read badly.
        label.set_wrap(True)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_max_width_chars(10)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_lines(2)
        cell.append(label)

        # The step the user is on is the one worth reading at a glance.
        if index != current:
            label.set_opacity(0.7)

        row.append(cell)

    row.update_property(
        [Gtk.AccessibleProperty.LABEL],
        [_("Step {number} of {total}").format(number=current + 1, total=len(steps))],
    )
    return row


def page_header(
    icon_name: str,
    title: str,
    subtitle: str,
    step: Optional[int] = None,
) -> Gtk.Box:
    """The title block at the top of an inner page."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    box.set_margin_bottom(4)

    box.append(icon_badge(icon_name, tone="accent", hero=True))

    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    text.set_valign(Gtk.Align.CENTER)
    text.set_hexpand(True)

    heading = Gtk.Label(label=title, xalign=0)
    heading.add_css_class("jb-page-title")
    heading.set_wrap(True)
    text.append(heading)

    sub = Gtk.Label(label=subtitle, xalign=0)
    sub.add_css_class("dim-label")
    sub.set_wrap(True)
    text.append(sub)

    box.append(text)

    if step is not None:
        box.append(step_indicator(step))

    return box


def hero(icon_name: str, title: str, subtitle: str) -> Gtk.Box:
    """The centred opening block, for the first and last screens."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_halign(Gtk.Align.CENTER)

    image = Gtk.Image.new_from_icon_name(resolve_icon(icon_name))
    image.add_css_class("jb-badge")
    image.add_css_class("jb-badge-accent")
    image.add_css_class("jb-badge-hero")
    image.add_css_class("jb-hero-icon")
    image.set_pixel_size(56)
    image.set_halign(Gtk.Align.CENTER)
    box.append(image)

    heading = Gtk.Label(label=title)
    heading.add_css_class("jb-hero-title")
    heading.set_wrap(True)
    heading.set_justify(Gtk.Justification.CENTER)
    box.append(heading)

    sub = Gtk.Label(label=subtitle)
    sub.add_css_class("dim-label")
    sub.set_wrap(True)
    sub.set_justify(Gtk.Justification.CENTER)
    box.append(sub)

    return box


def feature_strip(items: Sequence[Tuple[str, str, str]]) -> Gtk.Box:
    """A row of icon + label + hint, divided by thin separators.

    Args:
        items: (icon name, label, hint) for each entry.
    """
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    row.set_halign(Gtk.Align.CENTER)
    row.set_margin_top(6)

    for index, (icon_name, label, hint) in enumerate(items):
        if index:
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            sep.set_margin_start(18)
            sep.set_margin_end(18)
            sep.set_margin_top(4)
            sep.set_margin_bottom(4)
            row.append(sep)

        cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(22)
        image.set_valign(Gtk.Align.CENTER)
        image.add_css_class("dim-label")
        cell.append(image)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label=label, xalign=0)
        title.add_css_class("jb-feature-title")
        text.append(title)
        note = Gtk.Label(label=hint, xalign=0)
        note.add_css_class("dim-label")
        note.add_css_class("jb-footer")
        text.append(note)
        cell.append(text)

        row.append(cell)

    return row


def footer() -> Gtk.Box:
    """The signature line closing every page."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    box.set_halign(Gtk.Align.CENTER)
    box.set_margin_top(18)

    # The name is a brand, not a phrase to translate.
    label = Gtk.Label(
        label="{name}   •   {tagline}".format(
            name=APP_NAME, tagline=_("Bring Jellyfin to your big screen")
        )
    )
    label.add_css_class("dim-label")
    label.add_css_class("jb-footer")
    box.append(label)
    return box


def group(
    title: str, subtitle: str = "", icon_name: str = "", tone: str = ""
) -> Adw.PreferencesGroup:
    """A preferences group whose header carries an icon badge.

    Adw.PreferencesGroup has no icon slot, so the badge goes in the header
    suffix area and the text is left to the group itself -- which keeps the
    accessibility tree intact, unlike rebuilding the header by hand.
    """
    grp = Adw.PreferencesGroup()
    grp.set_title(title)
    if subtitle:
        grp.set_description(subtitle)
    if icon_name:
        grp.set_header_suffix(icon_badge(icon_name, tone=tone))
    return grp


__all__ = [
    "STEP_COMPLETE",
    "STEP_CONNECT",
    "STEP_DEVICE",
    "STEP_INSTALL",
    "feature_strip",
    "footer",
    "group",
    "hero",
    "icon_badge",
    "load_css",
    "page_header",
    "status_pill",
    "step_indicator",
]
