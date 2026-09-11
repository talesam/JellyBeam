# pages/install.py
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Vte", "3.91")

from gi.repository import Gtk, Adw, Vte, GLib, Pango, Gdk
from services.docker import DockerService
from services.device import DeviceService
from utils.i18n import _


class InstallPage(Gtk.Box):
    """Installation page with improved UX."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        self.window = window
        self.docker_service = DockerService(logger=window.logger)
        self.device_service = DeviceService(logger=window.logger)

        self.installation_running = False
        self._pulse_source_id = None

        self._setup_ui()

        # Connect to map signal to update device info when page is shown
        self.connect("map", self._on_page_shown)

    def _setup_ui(self):
        """Setup the installation page UI."""
        # ScrolledWindow to contain everything - prevents window from expanding
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(800)
        clamp.set_tightening_threshold(600)
        clamp.set_margin_top(32)
        clamp.set_margin_bottom(32)
        clamp.set_margin_start(32)
        clamp.set_margin_end(32)
        scroll.set_child(clamp)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clamp.set_child(main_box)

        # ============================================
        # HEADER
        # ============================================
        header_group = Adw.PreferencesGroup()
        header_group.set_title(_("Install Jellyfin"))
        header_group.set_description(_("One-click installation to your Samsung TV"))
        main_box.append(header_group)

        # TV Info row
        self.tv_info_row = Adw.ActionRow()
        self.tv_info_row.set_title(_("Target Device"))
        self.tv_info_row.set_subtitle(_("Loading..."))
        tv_icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        self.tv_info_row.add_prefix(tv_icon)
        header_group.add(self.tv_info_row)

        # ============================================
        # PROGRESS SECTION
        # ============================================
        self.progress_group = Adw.PreferencesGroup()
        self.progress_group.set_title(_("Installation Progress"))
        main_box.append(self.progress_group)

        # Status row
        self.status_row = Adw.ActionRow()
        self.status_row.set_title(_("Ready to install"))
        self.status_row.set_subtitle(_("Click the button below to start"))

        self.status_spinner = Gtk.Spinner()
        self.status_icon = Gtk.Image()
        self._current_prefix = None  # Track which prefix widget is attached

        self.progress_group.add(self.status_row)

        # Progress bar
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        progress_box.set_margin_top(8)
        progress_box.set_margin_bottom(4)
        progress_box.set_margin_start(16)
        progress_box.set_margin_end(16)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_show_text(False)
        self.progress_bar.add_css_class("osd")
        self.progress_bar.update_property(
            [
                Gtk.AccessibleProperty.LABEL,
                Gtk.AccessibleProperty.VALUE_NOW,
                Gtk.AccessibleProperty.VALUE_MIN,
                Gtk.AccessibleProperty.VALUE_MAX,
            ],
            [_("Installation progress"), 0.0, 0.0, 1.0],
        )
        progress_box.append(self.progress_bar)

        self.progress_label = Gtk.Label(label=_("Waiting to start..."))
        self.progress_label.add_css_class("dim-label")
        self.progress_label.set_halign(Gtk.Align.START)
        progress_box.append(self.progress_label)

        self.progress_group.add(progress_box)

        # Accessible live region — mirrors key status for screen readers
        self._live_region = Gtk.Label(label="")
        self._live_region.set_visible(False)
        self._live_region.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Installation status updates")],
        )
        progress_box.append(self._live_region)

        # ============================================
        # BUTTONS
        # ============================================
        self.button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.button_box.set_halign(Gtk.Align.CENTER)
        self.button_box.set_margin_top(8)
        self.button_box.set_margin_bottom(8)
        main_box.append(self.button_box)

        self.start_button = Gtk.Button.new_with_label(_("Install Jellyfin"))
        self.start_button.add_css_class("suggested-action")
        self.start_button.add_css_class("pill")
        self.start_button.set_size_request(160, 48)
        self.start_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Install Jellyfin on TV")]
        )
        self.start_button.connect("clicked", self._on_start_installation)
        self.button_box.append(self.start_button)

        self.cancel_button = Gtk.Button.new_with_label(_("Cancel"))
        self.cancel_button.add_css_class("destructive-action")
        self.cancel_button.add_css_class("pill")
        self.cancel_button.set_size_request(120, 48)
        self.cancel_button.set_sensitive(False)
        self.cancel_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Cancel installation")]
        )
        self.cancel_button.connect("clicked", self._on_cancel_installation)
        self.button_box.append(self.cancel_button)

        # ============================================
        # TERMINAL (COLLAPSIBLE)
        # ============================================
        terminal_group = Adw.PreferencesGroup()
        main_box.append(terminal_group)

        self.terminal_expander = Adw.ExpanderRow()
        self.terminal_expander.set_title(_("Installation Log"))
        self.terminal_expander.set_subtitle(_("Click to view detailed output"))
        log_icon = Gtk.Image.new_from_icon_name("utilities-terminal-symbolic")
        self.terminal_expander.add_prefix(log_icon)
        terminal_group.add(self.terminal_expander)

        # Terminal inside expander
        self.terminal_frame = Gtk.Frame()
        self.terminal_frame.set_size_request(-1, 250)

        self.terminal = Vte.Terminal()
        self.terminal.set_font(Pango.FontDescription("monospace 10"))
        self.terminal.set_scroll_on_output(True)
        self.terminal.set_scrollback_lines(2000)
        self._apply_terminal_colors()

        style_manager = Adw.StyleManager.get_default()
        style_manager.connect("notify::dark", lambda *_: self._apply_terminal_colors())

        terminal_scroll = Gtk.ScrolledWindow()
        terminal_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        terminal_scroll.set_child(self.terminal)
        self.terminal_frame.set_child(terminal_scroll)

        # Add terminal frame as a row in expander
        terminal_row = Adw.ActionRow()
        terminal_row.set_child(self.terminal_frame)
        self.terminal_expander.add_row(terminal_row)

        # ============================================
        # SUCCESS SECTION
        # ============================================
        self.success_group = Adw.PreferencesGroup()
        self.success_group.set_title(_("Installation Complete!"))
        self.success_group.set_visible(False)
        main_box.append(self.success_group)

        success_row = Adw.ActionRow()
        success_row.set_title(_("Jellyfin is ready!"))
        success_row.set_subtitle(_("Open the Jellyfin app on your TV"))
        success_icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
        success_row.add_prefix(success_icon)

        done_button = Gtk.Button.new_with_label(_("Done"))
        done_button.set_valign(Gtk.Align.CENTER)
        done_button.add_css_class("suggested-action")
        done_button.connect("clicked", self._on_finish)
        success_row.add_suffix(done_button)

        self.success_group.add(success_row)

    def _clear_prefix(self) -> None:
        """Remove the current prefix widget from status_row."""
        if self._current_prefix is not None:
            self.status_row.remove(self._current_prefix)
            self._current_prefix = None

    def _show_spinner_prefix(self) -> None:
        """Replace prefix with a spinning indicator."""
        self._clear_prefix()
        self.status_spinner.start()
        self.status_row.add_prefix(self.status_spinner)
        self._current_prefix = self.status_spinner

    def _show_icon_prefix(self, icon_name: str) -> None:
        """Replace prefix with a static icon."""
        self._clear_prefix()
        self.status_spinner.stop()
        self.status_icon.set_from_icon_name(icon_name)
        self.status_row.add_prefix(self.status_icon)
        self._current_prefix = self.status_icon

    def _apply_terminal_colors(self) -> None:
        """Set terminal colors based on current dark/light theme."""
        style_manager = Adw.StyleManager.get_default()
        if style_manager.get_dark():
            fg = Gdk.RGBA(red=0.9, green=0.9, blue=0.9, alpha=1.0)
            bg = Gdk.RGBA(red=0.15, green=0.15, blue=0.18, alpha=1.0)
        else:
            fg = Gdk.RGBA(red=0.1, green=0.1, blue=0.1, alpha=1.0)
            bg = Gdk.RGBA(red=0.96, green=0.96, blue=0.96, alpha=1.0)
        self.terminal.set_color_foreground(fg)
        self.terminal.set_color_background(bg)

    def _on_page_shown(self, widget):
        """Called when page becomes visible - update device info."""
        self._update_tv_info()

    def _update_tv_info(self):
        """Update TV info display."""
        tv_ip = self.window.config_manager.get("device.ip")
        tv_name = self.window.config_manager.get("device.name", "")
        tv_model = self.window.config_manager.get("device.model", "")

        if tv_ip:
            # Show device name as title, IP and model as subtitle
            if tv_name:
                self.tv_info_row.set_title(tv_name)
                subtitle = f"IP: {tv_ip}"
                if tv_model:
                    subtitle += f" | {tv_model}"
                self.tv_info_row.set_subtitle(subtitle)
            else:
                self.tv_info_row.set_title(_("Target Device"))
                self.tv_info_row.set_subtitle(tv_ip)
        else:
            self.tv_info_row.set_title(_("Target Device"))
            self.tv_info_row.set_subtitle(_("No device selected - please go back"))

    def _on_start_installation(self, button):
        """Start the installation process."""
        if self.installation_running:
            return

        tv_ip = self.window.config_manager.get("device.ip")
        if not tv_ip:
            self._show_error(_("No TV configured. Please go back and select a device."))
            return

        self._update_tv_info()
        self.installation_running = True

        # Update UI
        self.start_button.set_sensitive(False)
        self.cancel_button.set_sensitive(True)
        self.success_group.set_visible(False)

        # Show spinner
        self._show_spinner_prefix()

        # Clear and show terminal
        self.terminal.reset(True, True)
        # Don't auto-expand terminal - user can click to see it

        # Start installation
        self._run_installation(tv_ip)

    def _run_installation(self, tv_ip):
        """Run the installation process."""
        self._log_header(_("Starting Installation"))
        self._log_info(f"Target: {tv_ip}")
        self._log_info("")

        # Step 1: Pull Docker image
        self._set_status(_("Downloading container..."), 0.1)
        self._log_info(_("Pulling Docker image..."))

        def on_image_ready(success, message):

            if not self.installation_running:
                return

            if not success:
                self._installation_failed(message)
                return

            self._log_success(_("Container ready!"))
            self._log_info("")

            # Step 2: Install to TV
            self._set_status(_("Installing to TV..."), 0.5)
            self._log_info(_("Connecting and installing..."))
            self._log_info(_("This may take a few minutes..."))
            self._log_info("")

            def on_install_complete(success, message):
                if success:
                    self._installation_complete()
                else:
                    self._installation_failed(message)

            def on_progress(msg):
                import re

                GLib.idle_add(self._log_info, msg)

                # Parse real progress from Docker output like "installing[95]"
                match = re.search(r"\[(\d+)\]", msg)
                if match:
                    percent = int(match.group(1))
                    # Scale: 30% base (pull done) + 70% * install progress
                    real_progress = 0.30 + (0.70 * percent / 100)
                    GLib.idle_add(self._set_status, _("Installing..."), real_progress)
                elif "download" in msg.lower():
                    GLib.idle_add(self._set_status, _("Downloading app..."), 0.35)
                elif "transfer" in msg.lower():
                    GLib.idle_add(self._set_status, _("Transferring..."), 0.50)
                elif "connect" in msg.lower():
                    GLib.idle_add(self._set_status, _("Connecting to TV..."), 0.32)
                elif "install completed" in msg.lower():
                    GLib.idle_add(self._set_status, _("Finishing..."), 0.98)

            self.docker_service.install_jellyfin_direct_async(
                tv_ip, on_install_complete, progress_callback=on_progress
            )

        def on_pull_progress(msg):
            GLib.idle_add(self._log_info, msg)
            # Parse docker pull layer progress
            msg_lower = msg.lower()
            if "pulling" in msg_lower or "download" in msg_lower:
                GLib.idle_add(self._set_status, _("Downloading container..."), 0.1)
            elif "extracting" in msg_lower:
                GLib.idle_add(self._set_status, _("Extracting layers..."), 0.2)
            elif "pull complete" in msg_lower:
                GLib.idle_add(self._set_status, _("Download complete"), 0.28)

        self.docker_service.prepare_environment_async(
            on_image_ready, progress_callback=on_pull_progress
        )

    def _set_status(self, text, progress):
        """Update status text and progress bar."""
        self.status_row.set_title(text)
        self._announce(text)
        # Only increase progress, never decrease
        current = self.progress_bar.get_fraction()
        if progress > current:
            self.progress_bar.set_fraction(progress)
            self.progress_bar.update_property(
                [Gtk.AccessibleProperty.VALUE_NOW], [progress]
            )
            self.progress_label.set_text(f"{int(progress * 100)}%")
        # Reset pulse timer — if no progress in 10s, start pulsing
        self._reset_pulse_timer()

    def _reset_pulse_timer(self):
        """Reset the pulse fallback timer."""
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
        if self.installation_running:
            self._pulse_source_id = GLib.timeout_add(10000, self._start_pulse)

    def _start_pulse(self):
        """Start pulsing the progress bar when no updates arrive."""
        if self.installation_running:
            self.progress_bar.pulse()
            self._pulse_source_id = GLib.timeout_add(500, self._start_pulse)
        return False

    def _stop_pulse_timer(self):
        """Stop any active pulse timer."""
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None

    def _announce(self, text: str) -> None:
        """Push text to the accessible live region for screen readers."""
        self._live_region.set_label(text)

    def _log_header(self, text):
        """Log a header to terminal."""
        line = "=" * 50
        header = f"\r\n\033[1;36m{line}\r\n  {text}\r\n{line}\033[0m\r\n"
        self.terminal.feed(header.encode("utf-8"))

    def _log_info(self, text):
        """Log info text to terminal."""
        self.terminal.feed(f"{text}\r\n".encode("utf-8"))

    def _log_success(self, text):
        """Log success text (green)."""
        self.terminal.feed(f"\033[1;32m✓ {text}\033[0m\r\n".encode("utf-8"))
        self._announce(text)

    def _log_error(self, text):
        """Log error text (red)."""
        self.terminal.feed(f"\033[1;31m✗ {text}\033[0m\r\n".encode("utf-8"))
        self._announce(text)

    def _show_error(self, message):
        """Show error in status."""
        self.status_row.set_title(_("Error"))
        self.status_row.set_subtitle(message)
        self._log_error(message)

    def _installation_complete(self):
        """Handle successful installation."""
        self.installation_running = False
        self._stop_pulse_timer()

        self.progress_bar.set_fraction(1.0)
        self.progress_bar.update_property([Gtk.AccessibleProperty.VALUE_NOW], [1.0])
        self.progress_label.set_text("100%")

        self._show_icon_prefix("object-select-symbolic")

        self.status_row.set_title(_("Installation Complete!"))
        self.status_row.set_subtitle(_("Jellyfin is now on your TV"))

        self.start_button.set_label(_("Reinstall"))
        self.start_button.set_sensitive(True)
        self.cancel_button.set_sensitive(False)
        self.success_group.set_visible(True)

        self._log_info("")
        self._log_success(_("Installation Complete!"))
        self._log_info(_("Find Jellyfin in your TV's app list."))

    def _installation_failed(self, message):
        """Handle installation failure."""
        self.installation_running = False
        self._stop_pulse_timer()

        self._show_icon_prefix("dialog-error-symbolic")

        self.status_row.set_title(_("Installation Failed"))
        self.status_row.set_subtitle(message)

        self.start_button.set_label(_("Retry"))
        self.start_button.set_sensitive(True)
        self.cancel_button.set_sensitive(False)

        self._log_info("")
        self._log_error(_("Installation Failed"))
        self._log_error(message)

    def _on_cancel_installation(self, button):
        """Cancel the installation."""
        if self.installation_running:
            self.installation_running = False
            self._stop_pulse_timer()
            self.docker_service.stop_all_processes()

            self._clear_prefix()
            self.status_spinner.stop()

            self.status_row.set_title(_("Cancelled"))
            self.status_row.set_subtitle(_("Installation was cancelled"))

            self.progress_bar.set_fraction(0.0)
            self.progress_bar.update_property([Gtk.AccessibleProperty.VALUE_NOW], [0.0])
            self.progress_label.set_text(_("Cancelled"))

            self.start_button.set_label(_("Install Jellyfin"))
            self.start_button.set_sensitive(True)
            self.cancel_button.set_sensitive(False)

            self._log_error(_("Installation cancelled"))

    def _on_finish(self, button):
        """Return to welcome page."""
        # Pop back to welcome page
        self.window.navigation_view.pop_to_tag("welcome")
