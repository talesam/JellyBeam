# utils/ui_helpers.py
"""
UI helper functions for error notifications and user feedback.

This module provides utilities for displaying error messages, success notifications,
and other user feedback in the GTK4/Libadwaita interface.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk
from utils.i18n import _

# Module-level logger for UI helpers
_logger = logging.getLogger(__name__)


class ErrorNotification:
    """Helper class for showing error notifications in the UI."""

    @staticmethod
    def show_toast(window: Any, message: str, timeout: int = 3) -> None:
        """
        Show a toast notification.

        Args:
            window: The parent window or widget with toast overlay
            message: The message to display
            timeout: Duration in seconds (default: 3)
        """
        try:
            toast = Adw.Toast.new(message)
            toast.set_timeout(timeout)

            # Try to find toast overlay
            if hasattr(window, "toast_overlay"):
                window.toast_overlay.add_toast(toast)
            elif hasattr(window, "window") and hasattr(window.window, "toast_overlay"):
                # For pages that have a window reference
                window.window.toast_overlay.add_toast(toast)
            else:
                # Fallback: try to find parent window
                parent = window
                while parent is not None:
                    if hasattr(parent, "toast_overlay"):
                        parent.toast_overlay.add_toast(toast)
                        return
                    parent = (
                        parent.get_parent() if hasattr(parent, "get_parent") else None
                    )

                # If no toast overlay found, log the message
                _logger.warning(f"Toast (no overlay found): {message}")

        except Exception as e:
            # Fallback if toast creation fails
            _logger.error(f"Toast error: {e}, Message: {message}")

    @staticmethod
    def show_error_dialog(
        parent: Any, title: str, message: str, details: Optional[str] = None
    ) -> Optional[Adw.AlertDialog]:
        """
        Show an error dialog.

        Args:
            parent: The parent window
            title: Dialog title
            message: Main error message
            details: Additional error details

        Returns:
            The created dialog
        """
        try:
            dialog = Adw.AlertDialog()
            dialog.set_heading(title)

            if details:
                dialog.set_body_use_markup(True)
                full_message = f"{message}\n\n<small>{details}</small>"
                dialog.set_body(full_message)
            else:
                dialog.set_body(message)

            dialog.add_response("ok", _("OK"))
            dialog.set_default_response("ok")
            dialog.set_close_response("ok")

            dialog.present(parent)
            return dialog

        except Exception as e:
            _logger.error(f"Error dialog error: {e}")
            return None

    @staticmethod
    def show_success_dialog(
        parent: Any, title: str, message: str
    ) -> Optional[Adw.AlertDialog]:
        """
        Show a success dialog.

        Args:
            parent: The parent window
            title: Dialog title
            message: Success message

        Returns:
            The created dialog
        """
        try:
            dialog = Adw.AlertDialog()
            dialog.set_heading(title)
            dialog.set_body(message)

            dialog.add_response("ok", _("OK"))
            dialog.set_default_response("ok")
            dialog.set_close_response("ok")

            dialog.present(parent)
            return dialog

        except Exception as e:
            _logger.error(f"Success dialog error: {e}")
            return None

    @staticmethod
    def show_confirmation_dialog(
        parent: Any,
        title: str,
        message: str,
        confirm_text: Optional[str] = None,
        cancel_text: Optional[str] = None,
    ) -> Optional[Adw.AlertDialog]:
        """
        Show a confirmation dialog.

        Args:
            parent: The parent window
            title: Dialog title
            message: Confirmation message
            confirm_text: Text for confirm button
            cancel_text: Text for cancel button

        Returns:
            The created dialog
        """
        if confirm_text is None:
            confirm_text = _("Confirm")
        if cancel_text is None:
            cancel_text = _("Cancel")

        try:
            dialog = Adw.AlertDialog()
            dialog.set_heading(title)
            dialog.set_body(message)

            dialog.add_response("cancel", cancel_text)
            dialog.add_response("confirm", confirm_text)

            dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            dialog.present(parent)
            return dialog

        except Exception as e:
            _logger.error(f"Confirmation dialog error: {e}")
            return None


class ProgressHelper:
    """Helper class for progress indicators."""

    @staticmethod
    def create_spinner() -> Gtk.Spinner:
        """Create a spinner widget."""
        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        spinner.start()
        return spinner

    @staticmethod
    def create_progress_bar() -> Gtk.ProgressBar:
        """Create a progress bar widget."""
        progress = Gtk.ProgressBar()
        progress.set_show_text(True)
        return progress


class StatusHelper:
    """Helper class for status indicators."""

    @staticmethod
    def create_status_row(
        title: str, subtitle: Optional[str] = None, icon_name: Optional[str] = None
    ) -> Optional[Adw.ActionRow]:
        """
        Create a status row for lists.

        Args:
            title: Row title
            subtitle: Row subtitle
            icon_name: Icon name for the row

        Returns:
            Adw.ActionRow or None if creation fails
        """
        try:
            row = Adw.ActionRow()
            row.set_title(title)

            if subtitle:
                row.set_subtitle(subtitle)

            if icon_name:
                icon = Gtk.Image.new_from_icon_name(icon_name)
                row.add_prefix(icon)

            return row

        except Exception as e:
            _logger.error(f"Error creating status row: {e}")
            return None

    @staticmethod
    def update_status_row(
        row: Adw.ActionRow,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        icon_name: Optional[str] = None,
    ) -> None:
        """
        Update an existing status row.

        Args:
            row: The row to update
            title: New title
            subtitle: New subtitle
            icon_name: New icon name
        """
        try:
            if title:
                row.set_title(title)

            if subtitle is not None:
                row.set_subtitle(subtitle)

            if icon_name:
                # Remove old prefix if exists
                first_child = row.get_first_child()
                if first_child and isinstance(first_child, Gtk.Image):
                    row.remove(first_child)

                # Add new icon
                icon = Gtk.Image.new_from_icon_name(icon_name)
                row.add_prefix(icon)

        except Exception as e:
            _logger.error(f"Error updating status row: {e}")
