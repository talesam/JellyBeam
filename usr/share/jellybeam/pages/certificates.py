# pages/certificates.py
import gi
import webbrowser

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio
from services.certificates import CertificateService
from utils.i18n import _
from utils.ui_helpers import ErrorNotification


class CertificatesPage(Gtk.ScrolledWindow):
    """Certificate management page with simplified UX - default certificates enabled."""

    def __init__(self, window):
        super().__init__()

        self.window = window
        self.cert_service = CertificateService(logger=window.logger)

        # Configure scrolled window
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_propagate_natural_height(False)
        self.set_propagate_natural_width(False)

        self._setup_ui()

    def _setup_ui(self):
        """Setup the certificates page UI with simplified flow."""
        # Use clamp for better layout
        clamp = Adw.Clamp()
        clamp.set_maximum_size(800)
        clamp.set_tightening_threshold(600)
        clamp.set_margin_top(24)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(24)
        clamp.set_margin_end(24)
        self.set_child(clamp)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(main_box)

        # ============================================
        # HEADER
        # ============================================
        header_group = Adw.PreferencesGroup()
        header_group.set_title(_("Developer Certificates"))
        header_group.set_description(
            _("Certificates are required to install apps on Samsung TVs")
        )
        main_box.append(header_group)

        # ============================================
        # DEFAULT CERTIFICATES OPTION (NEW - SIMPLIFIED)
        # ============================================
        self.default_group = Adw.PreferencesGroup()
        self.default_group.set_title(_("Certificate Mode"))
        main_box.append(self.default_group)

        # Toggle for using default certificates
        self.use_default_row = Adw.SwitchRow()
        self.use_default_row.set_title(_("Use Built-in Certificates"))
        self.use_default_row.set_subtitle(_("Recommended - No Tizen Studio required"))
        default_icon = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
        self.use_default_row.add_prefix(default_icon)

        # Load saved preference
        use_default = self.window.config_manager.get("certificates.use_default", True)
        self.use_default_row.set_active(use_default)
        self.use_default_row.connect("notify::active", self._on_use_default_changed)
        self.default_group.add(self.use_default_row)

        # Info about default certificates
        self.default_info = Adw.ActionRow()
        self.default_info.set_title(_("How it works"))
        self.default_info.set_subtitle(
            _(
                "The Docker container includes pre-configured certificates. You can install Jellyfin immediately without any setup."
            )
        )
        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        self.default_info.add_prefix(info_icon)
        self.default_group.add(self.default_info)

        # ============================================
        # CUSTOM CERTIFICATES SECTION (COLLAPSIBLE)
        # ============================================
        self.custom_group = Adw.PreferencesGroup()
        self.custom_group.set_title(_("Custom Certificates (Advanced)"))
        self.custom_group.set_description(
            _("Only needed if you want to use your own certificates")
        )
        main_box.append(self.custom_group)

        # Author certificate
        self.author_cert_row = Adw.ActionRow()
        self.author_cert_row.set_title(_("Author Certificate"))
        self.author_cert_row.set_subtitle(_("Select author.p12 file"))
        author_icon = Gtk.Image.new_from_icon_name("contact-new-symbolic")
        self.author_cert_row.add_prefix(author_icon)

        self.author_cert_button = Gtk.Button.new_with_label(_("Browse"))
        self.author_cert_button.set_valign(Gtk.Align.CENTER)
        self.author_cert_button.connect(
            "clicked", lambda b: self._browse_file("author")
        )
        self.author_cert_row.add_suffix(self.author_cert_button)
        self.custom_group.add(self.author_cert_row)

        # Distributor certificate
        self.dist_cert_row = Adw.ActionRow()
        self.dist_cert_row.set_title(_("Distributor Certificate"))
        self.dist_cert_row.set_subtitle(_("Select distributor.p12 file"))
        dist_icon = Gtk.Image.new_from_icon_name("emblem-documents-symbolic")
        self.dist_cert_row.add_prefix(dist_icon)

        self.dist_cert_button = Gtk.Button.new_with_label(_("Browse"))
        self.dist_cert_button.set_valign(Gtk.Align.CENTER)
        self.dist_cert_button.connect(
            "clicked", lambda b: self._browse_file("distributor")
        )
        self.dist_cert_row.add_suffix(self.dist_cert_button)
        self.custom_group.add(self.dist_cert_row)

        # Password (not persisted to disk for security)
        self.password_row = Adw.PasswordEntryRow()
        self.password_row.set_title(_("Certificate Password"))
        self.password_row.update_property(
            [Gtk.AccessibleProperty.DESCRIPTION],
            [_("Password for the author P12 certificate")],
        )
        self.password_row.connect("changed", self._on_password_changed)
        self.custom_group.add(self.password_row)

        # Help link
        help_row = Adw.ActionRow()
        help_row.set_title(_("Need help creating certificates?"))
        help_row.set_subtitle(_("View tutorial on Samsung Developer website"))
        help_icon = Gtk.Image.new_from_icon_name("help-browser-symbolic")
        help_row.add_prefix(help_icon)

        help_btn = Gtk.Button.new_with_label(_("View Guide"))
        help_btn.set_valign(Gtk.Align.CENTER)
        help_btn.connect(
            "clicked",
            lambda b: webbrowser.open(
                "https://developer.samsung.com/smarttv/develop/getting-started/setting-up-sdk/creating-certificates.html"
            ),
        )
        help_row.add_suffix(help_btn)
        self.custom_group.add(help_row)

        # ============================================
        # CONTINUE BUTTON
        # ============================================
        self.actions_group = Adw.PreferencesGroup()
        main_box.append(self.actions_group)

        self.continue_row = Adw.ActionRow()
        self.continue_row.set_title(_("Continue to Installation"))
        self.continue_row.set_subtitle(_("Proceed to install Jellyfin on your TV"))

        self.continue_button = Gtk.Button.new_with_label(_("Continue"))
        self.continue_button.set_valign(Gtk.Align.CENTER)
        self.continue_button.add_css_class("suggested-action")
        self.continue_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Continue to Installation")]
        )
        self.continue_button.connect("clicked", self._on_continue)
        self.continue_row.add_suffix(self.continue_button)
        self.actions_group.add(self.continue_row)

        # Load existing certificate info and update UI visibility
        self._load_certificate_info()
        self._update_ui_visibility()

    def _on_use_default_changed(self, switch, param):
        """Handle toggle between default and custom certificates."""
        use_default = switch.get_active()
        self.window.config_manager.set("certificates.use_default", use_default)
        self._update_ui_visibility()

    def _update_ui_visibility(self):
        """Update UI based on certificate mode selection."""
        use_default = self.use_default_row.get_active()

        # Show/hide custom certificate options
        self.custom_group.set_visible(not use_default)

        # Update continue button sensitivity
        if use_default:
            # Can always continue with default certificates
            self.continue_button.set_sensitive(True)
            self.continue_row.set_subtitle(
                _("Ready to install with built-in certificates")
            )
        else:
            # Check if custom certificates are configured
            self._check_certificate_completeness()

    def _browse_file(self, cert_type):
        """Browse for certificate file."""
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title(
            _("Select {cert_type} certificate").format(cert_type=cert_type)
        )

        # Set file filter for P12 files
        filter_p12 = Gtk.FileFilter()
        filter_p12.set_name(_("P12 Certificate Files"))
        filter_p12.add_pattern("*.p12")
        filter_p12.add_pattern("*.P12")

        filter_list = Gio.ListStore()
        filter_list.append(filter_p12)
        file_dialog.set_filters(filter_list)

        def on_file_selected(dialog, result):
            try:
                file = dialog.open_finish(result)
                if file:
                    file_path = file.get_path()
                    self._set_certificate_file(cert_type, file_path)
            except Exception as e:
                self.window.logger.error(f"Error selecting certificate file: {e}")

        file_dialog.open(self.window, None, on_file_selected)

    def _set_certificate_file(self, cert_type, file_path):
        """Set certificate file path."""
        config_key = f"certificates.{cert_type}_cert_path"
        self.window.config_manager.set(config_key, file_path)

        # Get just the filename for display
        filename = file_path.split("/")[-1]

        # Update UI with checkmark
        if cert_type == "author":
            self.author_cert_row.set_subtitle(
                _("✅ {filename}").format(filename=filename)
            )
            self.author_cert_button.set_label(_("Change"))
        else:
            self.dist_cert_row.set_subtitle(
                _("✅ {filename}").format(filename=filename)
            )
            self.dist_cert_button.set_label(_("Change"))

        self._check_certificate_completeness()

    def _on_password_changed(self, entry):
        """Handle password changes (kept in memory only, not persisted)."""
        self._check_certificate_completeness()

    def _load_certificate_info(self):
        """Load existing certificate information."""
        # Load author certificate
        author_path = self.window.config_manager.get("certificates.author_cert_path")
        if author_path:
            filename = author_path.split("/")[-1]
            self.author_cert_row.set_subtitle(
                _("✅ {filename}").format(filename=filename)
            )
            self.author_cert_button.set_label(_("Change"))

        # Load distributor certificate
        dist_path = self.window.config_manager.get("certificates.distributor_cert_path")
        if dist_path:
            filename = dist_path.split("/")[-1]
            self.dist_cert_row.set_subtitle(
                _("✅ {filename}").format(filename=filename)
            )
            self.dist_cert_button.set_label(_("Change"))

    def _check_certificate_completeness(self):
        """Check if all required certificate info is provided for custom mode."""
        author_path = self.window.config_manager.get("certificates.author_cert_path")
        dist_path = self.window.config_manager.get("certificates.distributor_cert_path")
        password = self.password_row.get_text()

        is_complete = all([author_path, dist_path, password])
        self.continue_button.set_sensitive(is_complete)

        if is_complete:
            self.continue_row.set_subtitle(
                _("Ready to install with custom certificates")
            )
        else:
            missing = []
            if not author_path:
                missing.append(_("author certificate"))
            if not dist_path:
                missing.append(_("distributor certificate"))
            if not password:
                missing.append(_("password"))
            self.continue_row.set_subtitle(
                _("Missing: {items}").format(items=", ".join(missing))
            )

    def _on_continue(self, button):
        """Continue to installation page."""
        self.window.navigate_to_page(self.window.install_page, _("Installation"))

    def _show_error(self, message):
        """Show error dialog for certificate errors (persistent, not auto-dismissing)."""
        self.window.logger.error(message)
        ErrorNotification.show_error_dialog(
            self.window, _("Certificate Error"), message
        )

    def _show_success(self, message):
        """Show success message."""
        self.window.logger.info(message)
        ErrorNotification.show_toast(self.window, message, timeout=3)
