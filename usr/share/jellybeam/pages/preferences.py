# pages/preferences.py
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw
from utils.i18n import _


class PreferencesPage(Adw.PreferencesDialog):
    """Application preferences dialog."""

    def __init__(self, window):
        super().__init__()

        self.window = window
        self.set_title(_("Preferences"))

        self._setup_ui()

    def _setup_ui(self):
        """Setup the preferences UI."""
        # General preferences page
        general_page = Adw.PreferencesPage()
        general_page.set_title(_("General"))
        general_page.set_icon_name("preferences-system-symbolic")
        self.add(general_page)

        # Docker settings
        docker_group = Adw.PreferencesGroup()
        docker_group.set_title(_("Docker Settings"))
        docker_group.set_description(_("Configure Docker behavior and settings"))
        general_page.add(docker_group)

        # Docker image
        docker_image_row = Adw.EntryRow()
        docker_image_row.set_title(_("Docker Image"))
        docker_image_row.set_text(
            self.window.config_manager.get(
                "docker.image", "jellyfin/jellyfin-tizen:latest"
            )
        )
        docker_image_row.connect(
            "changed",
            lambda e: self.window.config_manager.set("docker.image", e.get_text()),
        )
        docker_group.add(docker_image_row)

        # Auto-pull updates
        auto_pull_row = Adw.SwitchRow()
        auto_pull_row.set_title(_("Auto-pull Updates"))
        auto_pull_row.set_subtitle(_("Automatically pull the latest Docker image"))
        auto_pull_row.set_active(
            self.window.config_manager.get("docker.auto_pull", True)
        )
        auto_pull_row.connect(
            "notify::active",
            lambda s, p: self.window.config_manager.set(
                "docker.auto_pull", s.get_active()
            ),
        )
        docker_group.add(auto_pull_row)

        # Network settings
        network_group = Adw.PreferencesGroup()
        network_group.set_title(_("Network Settings"))
        network_group.set_description(_("Configure network scanning and timeouts"))
        general_page.add(network_group)

        # Scan timeout
        scan_timeout_row = Adw.SpinRow()
        scan_timeout_row.set_title(_("Scan Timeout"))
        scan_timeout_row.set_subtitle(
            _("Timeout for network device scanning (seconds)")
        )
        adjustment = Gtk.Adjustment(value=30, lower=5, upper=300, step_increment=5)
        scan_timeout_row.set_adjustment(adjustment)
        scan_timeout_row.set_value(
            self.window.config_manager.get("network.scan_timeout", 30)
        )
        scan_timeout_row.connect(
            "changed",
            lambda s: self.window.config_manager.set(
                "network.scan_timeout", int(s.get_value())
            ),
        )
        network_group.add(scan_timeout_row)

        # Port range - Fixed: ActionRow instead of EntryRow for subtitle
        port_range_row = Adw.ActionRow()
        port_range_row.set_title(_("Port Range"))
        port_range_row.set_subtitle(_("Scan port range (e.g., 8000-8080)"))

        port_range_entry = Gtk.Entry()
        port_range_entry.set_text(
            self.window.config_manager.get("network.port_range", "8000-8080")
        )
        port_range_entry.set_valign(Gtk.Align.CENTER)
        port_range_entry.set_max_width_chars(8)
        port_range_entry.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Port range for network scanning")]
        )
        port_range_entry.set_width_chars(8)
        port_range_entry.connect(
            "changed",
            lambda e: self.window.config_manager.set(
                "network.port_range", e.get_text()
            ),
        )
        port_range_row.add_suffix(port_range_entry)

        network_group.add(port_range_row)

        # Logging settings
        logging_group = Adw.PreferencesGroup()
        logging_group.set_title(_("Logging"))
        logging_group.set_description(_("Configure application logging"))
        general_page.add(logging_group)

        # Log level
        log_level_row = Adw.ComboRow()
        log_level_row.set_title(_("Log Level"))
        log_level_row.set_subtitle(_("Verbosity of application logs"))

        log_levels = Gtk.StringList()
        log_levels.append("DEBUG")
        log_levels.append("INFO")
        log_levels.append("WARNING")
        log_levels.append("ERROR")
        log_level_row.set_model(log_levels)

        current_level = self.window.config_manager.get("logging.level", "INFO")
        level_index = ["DEBUG", "INFO", "WARNING", "ERROR"].index(current_level)
        log_level_row.set_selected(level_index)
        log_level_row.connect("notify::selected", self._on_log_level_changed)
        logging_group.add(log_level_row)

        # Save logs
        save_logs_row = Adw.SwitchRow()
        save_logs_row.set_title(_("Save Logs to File"))
        save_logs_row.set_subtitle(
            _("Save application logs to ~/.local/share/jellybeam/logs")
        )
        save_logs_row.set_active(
            self.window.config_manager.get("logging.save_to_file", True)
        )
        save_logs_row.connect(
            "notify::active",
            lambda s, p: self.window.config_manager.set(
                "logging.save_to_file", s.get_active()
            ),
        )
        logging_group.add(save_logs_row)

        # Advanced settings page
        advanced_page = Adw.PreferencesPage()
        advanced_page.set_title(_("Advanced"))
        advanced_page.set_icon_name("preferences-system-details-symbolic")
        self.add(advanced_page)

        # Developer options
        dev_group = Adw.PreferencesGroup()
        dev_group.set_title(_("Developer Options"))
        dev_group.set_description(_("Advanced settings for developers"))
        advanced_page.add(dev_group)

        # Debug mode
        debug_mode_row = Adw.SwitchRow()
        debug_mode_row.set_title(_("Debug Mode"))
        debug_mode_row.set_subtitle(_("Enable debug mode for development"))
        debug_mode_row.set_active(
            self.window.config_manager.get("debug.enabled", False)
        )
        debug_mode_row.connect(
            "notify::active",
            lambda s, p: self.window.config_manager.set(
                "debug.enabled", s.get_active()
            ),
        )
        dev_group.add(debug_mode_row)

        # Reset settings
        reset_group = Adw.PreferencesGroup()
        reset_group.set_title(_("Reset"))
        reset_group.set_description(_("Reset application settings"))
        advanced_page.add(reset_group)

        reset_row = Adw.ActionRow()
        reset_row.set_title(_("Reset All Settings"))
        reset_row.set_subtitle(_("Reset all preferences to default values"))

        reset_button = Gtk.Button.new_with_label(_("Reset"))
        reset_button.set_valign(Gtk.Align.CENTER)
        reset_button.add_css_class("destructive-action")
        reset_button.connect("clicked", self._on_reset_settings)
        reset_row.add_suffix(reset_button)

        reset_group.add(reset_row)

    def _on_log_level_changed(self, combo_row, param):
        """Handle log level change."""
        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        selected_level = levels[combo_row.get_selected()]
        self.window.config_manager.set("logging.level", selected_level)

        # Update logger level
        self.window.logger.set_level(selected_level)

    def _on_reset_settings(self, button):
        """Reset all settings to defaults."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Reset All Settings?"))
        dialog.set_body(
            _(
                "This will reset all preferences to their default values. This action cannot be undone."
            )
        )

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Reset"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(dialog, response):
            if response == "reset":
                self.window.config_manager.reset_to_defaults()
                self.close()

        dialog.connect("response", on_response)
        dialog.present(self)
