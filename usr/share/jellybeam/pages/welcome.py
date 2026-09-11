# pages/welcome.py
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib
from services.docker import DockerService
from utils.i18n import _


class WelcomePage(Gtk.Box):
    """Welcome page with Docker verification - simplified layout."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.window = window
        self.docker_service = DockerService(logger=window.logger)

        self.set_hexpand(True)
        self.set_vexpand(True)

        self._setup_ui()
        self._check_dependencies()

    def _setup_ui(self):
        """Setup the welcome page UI."""
        # Create a clamp to center content
        clamp = Adw.Clamp()
        clamp.set_maximum_size(700)
        clamp.set_tightening_threshold(500)
        clamp.set_margin_top(32)
        clamp.set_margin_bottom(32)
        clamp.set_margin_start(32)
        clamp.set_margin_end(32)
        self.append(clamp)

        # Main content box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32)
        clamp.set_child(main_box)

        # ============================================
        # HEADER
        # ============================================
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        header_box.set_halign(Gtk.Align.CENTER)
        header_box.set_margin_top(24)
        header_box.set_margin_bottom(24)
        main_box.append(header_box)

        # Icon - larger
        icon = Gtk.Image.new_from_icon_name("tv-symbolic")
        icon.set_pixel_size(96)
        icon.add_css_class("dim-label")
        header_box.append(icon)

        # Title - larger
        title = Gtk.Label(label=_("JellyBeam Installer"))
        title.add_css_class("title-1")
        header_box.append(title)

        # Description
        desc = Gtk.Label(
            label=_("Install Jellyfin on your Samsung Smart TV or projector")
        )
        desc.add_css_class("dim-label")
        desc.set_wrap(True)
        desc.set_justify(Gtk.Justification.CENTER)
        header_box.append(desc)

        # ============================================
        # FIRST-RUN ONBOARDING BANNER
        # ============================================
        if self.window.config_manager.get("app.first_run", True):
            onboarding_group = Adw.PreferencesGroup()
            onboarding_group.set_title(_("How it works"))
            onboarding_group.set_description(
                _("4 simple steps to get Jellyfin on your Samsung TV")
            )
            main_box.append(onboarding_group)

            steps = [
                ("1", _("Check Requirements"), _("Ensure Docker is installed")),
                ("2", _("Connect Device"), _("Find your TV on the network")),
                ("3", _("Certificates"), _("Configure signing (auto by default)")),
                ("4", _("Install"), _("One click to deploy Jellyfin")),
            ]
            for num, title_text, subtitle_text in steps:
                row = Adw.ActionRow()
                row.set_title(title_text)
                row.set_subtitle(subtitle_text)
                badge = Gtk.Label(label=num)
                badge.add_css_class("accent")
                badge.add_css_class("heading")
                row.add_prefix(badge)
                onboarding_group.add(row)

            self._onboarding_group = onboarding_group
            self.window.config_manager.set("app.first_run", False)

        # ============================================
        # REQUIREMENTS - In same flow
        # ============================================
        self.requirements_group = Adw.PreferencesGroup()
        self.requirements_group.set_title(_("System Requirements"))
        main_box.append(self.requirements_group)

        # Docker status row
        self.docker_row = Adw.ActionRow()
        self.docker_row.set_title(_("Docker Engine"))
        self.docker_row.set_subtitle(_("Checking..."))

        self.docker_spinner = Gtk.Spinner()
        self.docker_spinner.start()
        self.docker_row.add_suffix(self.docker_spinner)

        self.requirements_group.add(self.docker_row)

        # Install Docker row (initially not added)
        self.install_docker_row = Adw.ActionRow()
        self.install_docker_row.set_title(_("Install Docker"))
        self.install_docker_row.set_subtitle(_("Docker is required but not installed"))

        self.install_docker_button = Gtk.Button.new_with_label(_("Install"))
        self.install_docker_button.set_valign(Gtk.Align.CENTER)
        self.install_docker_button.add_css_class("flat")
        self.install_docker_button.connect("clicked", self._on_install_docker)
        self.install_docker_row.add_suffix(self.install_docker_button)

        # Docker group row (for when user is not in docker group)
        self.docker_group_row = Adw.ActionRow()
        self.docker_group_row.set_title(_("Docker Group"))
        self.docker_group_row.set_subtitle(_("User not in docker group"))

        self.add_group_button = Gtk.Button.new_with_label(_("Add to group"))
        self.add_group_button.set_valign(Gtk.Align.CENTER)
        self.add_group_button.add_css_class("flat")
        self.add_group_button.connect("clicked", self._on_add_to_docker_group)
        self.docker_group_row.add_suffix(self.add_group_button)

        # ============================================
        # CONTINUE BUTTON
        # ============================================
        self.actions_group = Adw.PreferencesGroup()
        main_box.append(self.actions_group)

        self.continue_row = Adw.ActionRow()
        self.continue_row.set_title(_("Continue"))
        self.continue_row.set_subtitle(_("Configure your Samsung TV"))

        self.continue_button = Gtk.Button.new_with_label(_("Continue"))
        self.continue_button.set_valign(Gtk.Align.CENTER)
        self.continue_button.add_css_class("suggested-action")
        self.continue_button.set_sensitive(False)
        self.continue_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Continue to Device Setup")]
        )
        self.continue_button.connect("clicked", self._on_continue)
        self.continue_row.add_suffix(self.continue_button)

        self.actions_group.add(self.continue_row)

    def _check_dependencies(self):
        """Check if all required dependencies are installed."""
        GLib.timeout_add(500, self._check_docker_status)

    def _check_docker_status(self):
        """Check Docker installation, group membership, and status."""
        try:
            is_installed = self.docker_service.is_docker_installed()
            is_in_group = (
                self.docker_service.is_user_in_docker_group() if is_installed else False
            )
            is_running = (
                self.docker_service.is_docker_running() if is_installed else False
            )

            self.docker_spinner.stop()
            self.docker_row.remove(self.docker_spinner)

            if is_installed and is_running:
                # Docker is ready
                success_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                success_icon.add_css_class("success")
                self.docker_row.add_suffix(success_icon)
                self.docker_row.set_subtitle(_("Ready"))
                self.continue_button.set_sensitive(True)

            elif is_installed and not is_in_group:
                # Docker installed but user not in docker group
                warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
                self.docker_row.add_suffix(warning_icon)
                self.docker_row.set_subtitle(_("Permission required"))
                self.requirements_group.add(self.docker_group_row)

            elif is_installed and not is_running:
                # Docker installed but not running
                warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
                self.docker_row.add_suffix(warning_icon)
                self.docker_row.set_subtitle(_("Not running"))

                start_button = Gtk.Button.new_with_label(_("Start"))
                start_button.set_valign(Gtk.Align.CENTER)
                start_button.connect("clicked", self._on_start_docker)
                self.docker_row.add_suffix(start_button)

            else:
                # Docker not installed
                error_icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
                self.docker_row.add_suffix(error_icon)
                self.docker_row.set_subtitle(_("Not installed"))
                self.requirements_group.add(self.install_docker_row)

        except Exception as e:
            self.window.logger.error(f"Error checking Docker status: {e}")

        return False

    def _on_install_docker(self, button):
        """Handle Docker installation."""
        install_dialog = DockerInstallDialog(self.window, self)
        install_dialog.present(self.window)

    def _on_start_docker(self, button):
        """Handle starting Docker service."""
        button.set_sensitive(False)
        spinner = Gtk.Spinner()
        spinner.start()
        self.docker_row.add_suffix(spinner)

        def on_docker_started(success):
            button.set_sensitive(True)
            self.docker_row.remove(spinner)
            if success:
                self._check_docker_status()

        self.docker_service.start_docker_async(on_docker_started)

    def _on_add_to_docker_group(self, button):
        """Handle adding user to docker group."""
        button.set_sensitive(False)
        spinner = Gtk.Spinner()
        spinner.start()
        self.docker_group_row.add_suffix(spinner)

        def on_group_added(success, message):
            spinner.stop()
            self.docker_group_row.remove(spinner)

            if success:
                # Remove the group row and restart check
                try:
                    self.requirements_group.remove(self.docker_group_row)
                except Exception:
                    pass

                # Show success message
                self.docker_group_row.set_subtitle(_("Added to group"))

                # Re-check docker status (group is now applied)
                # Reset the docker row first
                self._reset_docker_row()
                self._check_docker_status()
            else:
                button.set_sensitive(True)
                self.docker_group_row.set_subtitle(message)

        self.docker_service.add_user_to_docker_group_async(on_group_added)

    def _reset_docker_row(self):
        """Reset the docker row for re-checking."""
        # Remove all suffixes except the first one (if any)
        while True:
            suffix = self.docker_row.get_last_child()
            if suffix and suffix != self.docker_row.get_first_child():
                # Check if it's a suffix widget (not the title/subtitle)
                if isinstance(suffix, (Gtk.Image, Gtk.Button, Gtk.Spinner)):
                    self.docker_row.remove(suffix)
                else:
                    break
            else:
                break

        # Add spinner again
        self.docker_spinner = Gtk.Spinner()
        self.docker_spinner.start()
        self.docker_row.add_suffix(self.docker_spinner)
        self.docker_row.set_subtitle(_("Checking..."))

    def _on_continue(self, button):
        """Navigate to device setup page."""
        self.window.navigate_to_page(self.window.device_page, _("Device Setup"))


class DockerInstallDialog(Adw.AlertDialog):
    """Dialog for Docker installation guidance."""

    def __init__(self, window, welcome_page):
        super().__init__()

        self.window = window
        self.welcome_page = welcome_page
        self.set_heading(_("Install Docker"))
        self.set_body(
            _(
                "Select your distribution:\n\n"
                "⚠ This will require elevated privileges (sudo). "
                "You may be prompted for your password."
            )
        )

        self.add_response("cancel", _("Cancel"))
        self.add_response("arch", _("Arch/Manjaro"))
        self.add_response("debian", _("Debian/Ubuntu"))
        self.add_response("fedora", _("Fedora/RHEL"))

        self.set_default_response("cancel")
        self.connect("response", self._on_response)

    def _on_response(self, dialog, response):
        """Handle dialog response — starts async Docker installation."""
        if response == "cancel":
            self.close()
            return

        self.close()

        # Update welcome page to show installation progress
        self.welcome_page.install_docker_button.set_sensitive(False)
        self.welcome_page.install_docker_row.set_subtitle(_("Installing Docker..."))

        install_spinner = Gtk.Spinner()
        install_spinner.start()
        self.welcome_page.install_docker_row.add_suffix(install_spinner)

        docker_service = DockerService(logger=self.window.logger)

        def on_progress(msg):
            GLib.idle_add(self.welcome_page.install_docker_row.set_subtitle, msg)

        def on_complete(success, message):
            self.welcome_page.install_docker_row.remove(install_spinner)

            if success:
                self.welcome_page.install_docker_row.set_subtitle(
                    _("Docker installed! Checking status...")
                )
                # Re-check everything
                self.welcome_page._reset_docker_row()
                self.welcome_page._check_docker_status()
            else:
                self.welcome_page.install_docker_button.set_sensitive(True)
                self.welcome_page.install_docker_row.set_subtitle(
                    _("Installation failed: {msg}").format(msg=message)
                )

        docker_service.install_docker_async(
            response, on_complete, progress_callback=on_progress
        )
