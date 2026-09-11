# pages/device.py
import gi
import socket

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib
from services.device import DeviceService
from utils.validators import NetworkValidator
from utils.i18n import _
from utils.ui_helpers import ErrorNotification


class DevicePage(Gtk.ScrolledWindow):
    """Device discovery and connection page with improved UX flow."""

    def __init__(self, window):
        super().__init__()

        self.window = window
        self.device_service = DeviceService(logger=window.logger)
        self.validator = NetworkValidator()

        # Keep track of device rows for proper cleanup
        self.device_rows = []

        # Configure scrolled window to prevent window resize
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_propagate_natural_height(False)
        self.set_propagate_natural_width(False)

        self._setup_ui()

    def _setup_ui(self):
        """Setup the device page UI with inline developer mode instructions."""
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

        # Header
        header_group = Adw.PreferencesGroup()
        header_group.set_title(_("Device Setup"))
        header_group.set_description(_("Connect to your Samsung Tizen TV or projector"))
        main_box.append(header_group)

        # ============================================
        # DEVELOPER MODE INSTRUCTIONS (COLLAPSIBLE)
        # ============================================
        instructions_group = Adw.PreferencesGroup()
        instructions_group.set_title(_("Setup Instructions"))
        main_box.append(instructions_group)

        # Main expander for instructions
        self.instructions_expander = Adw.ExpanderRow()
        self.instructions_expander.set_title(_("Enable Developer Mode on TV"))
        self.instructions_expander.set_subtitle(
            _("Click to view step-by-step instructions")
        )
        expander_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        expander_icon.add_css_class("warning")
        self.instructions_expander.add_prefix(expander_icon)
        instructions_group.add(self.instructions_expander)

        # Step 1
        step1 = Adw.ActionRow()
        step1.set_title(_("1. Open Apps"))
        step1.set_subtitle(_("On the TV, go to the 'Apps' section"))
        self.instructions_expander.add_row(step1)

        # Step 2
        step2 = Adw.ActionRow()
        step2.set_title(_("2. Go to App Settings"))
        step2.set_subtitle(_("Scroll to the end and select 'App Settings'"))
        self.instructions_expander.add_row(step2)

        # Step 3
        step3 = Adw.ActionRow()
        step3.set_title(_("3. Press '123' Button"))
        step3.set_subtitle(_("Press the '123' button on your remote"))
        self.instructions_expander.add_row(step3)

        # Step 4
        step4 = Adw.ActionRow()
        step4.set_title(_("4. Enter Code '12345'"))
        step4.set_subtitle(_("Developer Mode menu will appear"))
        self.instructions_expander.add_row(step4)

        # Step 5
        step5 = Adw.ActionRow()
        step5.set_title(_("5. Enable Developer Mode"))
        step5.set_subtitle(_("Toggle 'Developer Mode' to 'On'"))
        self.instructions_expander.add_row(step5)

        # Step 6 - With IP address
        local_ip = self._get_local_ip()
        step6 = Adw.ActionRow()
        step6.set_title(_("6. Enter This IP: {ip}").format(ip=local_ip))
        step6.set_subtitle(_("Your computer's IP address"))

        self.copy_button = Gtk.Button.new_with_label(_("Copy IP"))
        self.copy_button.set_valign(Gtk.Align.CENTER)
        self.copy_button.add_css_class("suggested-action")
        self.copy_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Copy local IP address to clipboard")]
        )
        self.copy_button.connect("clicked", self._copy_ip_to_clipboard)
        step6.add_suffix(self.copy_button)
        self.instructions_expander.add_row(step6)

        # Step 7
        step7 = Adw.ActionRow()
        step7.set_title(_("7. Restart TV"))
        step7.set_subtitle(_("Turn off and on your TV"))
        self.instructions_expander.add_row(step7)

        # ============================================
        # DEVELOPER MODE CONFIRMATION (MANDATORY)
        # ============================================
        self.confirm_group = Adw.PreferencesGroup()
        self.confirm_group.set_title(_("Confirmation"))
        main_box.append(self.confirm_group)

        # Developer mode confirmation toggle
        self.dev_mode_row = Adw.ActionRow()
        self.dev_mode_row.set_title(_("Developer Mode Enabled"))
        self.dev_mode_row.set_subtitle(
            _("I confirm I have completed the steps above on my TV")
        )

        # Developer mode switch
        self.dev_mode_switch = Gtk.Switch()
        self.dev_mode_switch.set_valign(Gtk.Align.CENTER)
        self.dev_mode_switch.set_active(
            self.window.config_manager.get("device.developer_mode", False)
        )
        self.dev_mode_switch.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Developer Mode Enabled")]
        )
        self.dev_mode_switch.connect("notify::active", self._on_dev_mode_changed)
        self.dev_mode_row.add_suffix(self.dev_mode_switch)

        self.confirm_group.add(self.dev_mode_row)

        # ============================================
        # DISCOVERY SECTION
        # ============================================
        self.discovery_group = Adw.PreferencesGroup()
        self.discovery_group.set_title(_("Device Discovery"))
        self.discovery_group.set_visible(False)
        main_box.append(self.discovery_group)

        # Scan network row
        self.scan_row = Adw.ActionRow()
        self.scan_row.set_title(_("Scan Network"))
        self.scan_row.set_subtitle(
            _("Automatically discover Samsung devices on your network")
        )

        self.scan_button = Gtk.Button.new_with_label(_("Scan"))
        self.scan_button.set_valign(Gtk.Align.CENTER)
        self.scan_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Scan network for Samsung devices")]
        )
        self.scan_button.connect("clicked", self._on_scan_network)
        self.scan_row.add_suffix(self.scan_button)

        self.discovery_group.add(self.scan_row)

        # Discovered devices list
        self.devices_group = Adw.PreferencesGroup()
        self.devices_group.set_title(_("Discovered Devices"))
        self.devices_group.set_description(_("Select your target device"))
        self.devices_group.set_visible(False)
        main_box.append(self.devices_group)

        # ============================================
        # MANUAL CONNECTION SECTION
        # ============================================
        self.manual_group = Adw.PreferencesGroup()
        self.manual_group.set_title(_("Manual Connection"))
        self.manual_group.set_description(_("Enter device details manually"))
        self.manual_group.set_visible(False)
        main_box.append(self.manual_group)

        # IP address entry
        self.ip_row = Adw.EntryRow()
        self.ip_row.set_title(_("Device IP Address"))
        self.ip_row.set_text("")
        self.ip_row.update_property(
            [Gtk.AccessibleProperty.DESCRIPTION],
            [_("Enter the Samsung TV IP address, for example 192.168.1.100")],
        )
        self.ip_row.connect("changed", self._on_ip_changed)
        self.manual_group.add(self.ip_row)

        # ============================================
        # ACTIONS
        # ============================================
        self.actions_group = Adw.PreferencesGroup()
        self.actions_group.set_visible(False)
        main_box.append(self.actions_group)

        # Connect button - DISABLED until developer mode is confirmed
        self.connect_row = Adw.ActionRow()
        self.connect_row.set_title(_("Connect to Device"))
        self.connect_row.set_subtitle(_("Establish connection with your TV"))

        self.connect_button = Gtk.Button.new_with_label(_("Connect"))
        self.connect_button.set_valign(Gtk.Align.CENTER)
        self.connect_button.add_css_class("suggested-action")
        self.connect_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Connect to Samsung TV")]
        )
        # Initially disabled - only enabled when developer mode is confirmed
        self.connect_button.set_sensitive(self.dev_mode_switch.get_active())
        self.connect_button.connect("clicked", self._on_connect_device)
        self.connect_row.add_suffix(self.connect_button)

        self.actions_group.add(self.connect_row)

        # Continue button (initially disabled)
        self.continue_row = Adw.ActionRow()
        self.continue_row.set_title(_("Continue to Certificates"))
        self.continue_row.set_subtitle(_("Setup developer certificates"))

        self.continue_button = Gtk.Button.new_with_label(_("Continue"))
        self.continue_button.set_valign(Gtk.Align.CENTER)
        self.continue_button.add_css_class("suggested-action")
        self.continue_button.set_sensitive(False)
        self.continue_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Continue to Certificates")]
        )
        self.continue_button.connect("clicked", self._on_continue)
        self.continue_row.add_suffix(self.continue_button)

        self.actions_group.add(self.continue_row)

        # Show sections if developer mode was already enabled (saved state)
        if self.dev_mode_switch.get_active():
            self.discovery_group.set_visible(True)
            self.actions_group.set_visible(True)
            # manual_group stays hidden until scan finds nothing

    def _get_local_ip(self):
        """Get local IP address."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(1)
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return _("Unable to determine IP")

    def _copy_ip_to_clipboard(self, button):
        """Copy IP to clipboard."""
        ip = self._get_local_ip()
        clipboard = self.window.get_clipboard()
        clipboard.set(ip)
        original_label = self.copy_button.get_label()
        self.copy_button.set_label(_("Copied!"))
        GLib.timeout_add(2000, lambda: self.copy_button.set_label(original_label))

    def _on_scan_network(self, button):
        """Scan network for Samsung devices."""
        # Disable button and show spinner
        self.scan_button.set_sensitive(False)
        self.scan_button.set_label(_("Scanning..."))

        # Create and start spinner
        self.scan_spinner = Gtk.Spinner()
        self.scan_spinner.start()
        self.scan_row.add_suffix(self.scan_spinner)

        def on_scan_complete(devices):
            # Re-enable button and remove spinner
            self.scan_button.set_sensitive(True)
            self.scan_button.set_label(_("Scan"))
            self.scan_row.remove(self.scan_spinner)
            self._update_devices_list(devices)

        self.device_service.scan_network_async(on_scan_complete)

    def _update_devices_list(self, devices):
        """Update the discovered devices list."""
        # Clear existing device rows properly
        for row in self.device_rows:
            self.devices_group.remove(row)
        self.device_rows.clear()

        # Show the group now that a scan has completed
        self.devices_group.set_visible(True)

        if not devices:
            no_devices_row = Adw.ActionRow()
            no_devices_row.set_title(_("No devices found"))
            no_devices_row.set_subtitle(_("Try manual connection or check network"))
            self.devices_group.add(no_devices_row)
            self.device_rows.append(no_devices_row)
            # Show manual connection as fallback
            self.manual_group.set_visible(True)
            return

        for device in devices:
            device_row = Adw.ActionRow()
            device_row.set_title(device.get("name", _("Unknown Device")))
            device_row.set_subtitle(
                _("IP: {ip} | Model: {model}").format(
                    ip=device["ip"], model=device.get("model", _("Unknown"))
                )
            )

            select_button = Gtk.Button.new_with_label(_("Select"))
            select_button.set_valign(Gtk.Align.CENTER)
            select_button.connect("clicked", lambda b, d=device: self._select_device(d))
            device_row.add_suffix(select_button)

            self.devices_group.add(device_row)
            self.device_rows.append(device_row)

        # Update devices group description with count
        device_count = len(devices)
        if device_count == 1:
            desc = _("Found 1 device - Select your target device")
        else:
            desc = _("Found {count} devices - Select your target device").format(
                count=device_count
            )
        self.devices_group.set_description(desc)
        # Announce to screen readers
        self.devices_group.update_property([Gtk.AccessibleProperty.LABEL], [desc])

    def _select_device(self, device):
        """Select a discovered device."""
        ip = device["ip"]
        name = device.get("name", "")
        model = device.get("model", "")

        self.ip_row.set_text(ip)
        self.window.config_manager.set("device.ip", ip)
        self.window.config_manager.set("device.name", name)
        self.window.config_manager.set("device.model", model)

        self.window.logger.info(f"Selected device: {name} ({ip})")
        self._show_success(_("Device selected: {name}").format(name=name or ip))

    def _on_ip_changed(self, entry):
        """Handle IP address changes."""
        ip = entry.get_text()
        self.window.config_manager.set("device.ip", ip)

        # Validate IP
        is_valid = self.validator.is_valid_ip(ip)
        if ip and not is_valid:
            entry.add_css_class("error")
            entry.set_title(
                _("Device IP Address — Invalid format (e.g. 192.168.1.100)")
            )
        else:
            entry.remove_css_class("error")
            entry.set_title(_("Device IP Address"))

        # Update connect button: requires dev mode + non-empty IP
        dev_mode = self.dev_mode_switch.get_active()
        self.connect_button.set_sensitive(dev_mode and len(ip.strip()) > 0)

    def _on_dev_mode_changed(self, switch, param):
        """Handle developer mode toggle - reveals connection sections."""
        is_active = switch.get_active()
        self.window.config_manager.set("device.developer_mode", is_active)

        # Show/hide sections based on developer mode
        self.discovery_group.set_visible(is_active)
        self.actions_group.set_visible(is_active)
        # manual_group stays hidden until scan finds nothing
        if not is_active:
            self.manual_group.set_visible(False)
            self.devices_group.set_visible(False)

        # Enable connect button only when developer mode is confirmed and IP present
        ip = self.ip_row.get_text().strip()
        self.connect_button.set_sensitive(is_active and len(ip) > 0)

    def _on_connect_device(self, button):
        """Connect to the device."""
        ip = self.ip_row.get_text().strip()

        if not ip:
            self._show_error(_("Please enter a device IP address"))
            return

        if not self.validator.is_valid_ip(ip):
            self._show_error(_("Please enter a valid IP address"))
            return

        # Disable button and show spinner
        self.connect_button.set_sensitive(False)
        self.connect_button.set_label(_("Connecting..."))

        self.connect_spinner = Gtk.Spinner()
        self.connect_spinner.start()
        self.connect_row.add_suffix(self.connect_spinner)

        def on_connection_result(success, message):
            # Re-enable button and remove spinner
            self.connect_button.set_sensitive(True)
            self.connect_button.set_label(_("Connect"))
            self.connect_row.remove(self.connect_spinner)

            if success:
                self.continue_button.set_sensitive(True)
                self._show_success(_("Connected successfully!"))
            else:
                ErrorNotification.show_error_dialog(
                    self.window,
                    _("Connection Failed"),
                    _("Connection failed: {message}").format(message=message),
                )

        dev_mode = self.dev_mode_switch.get_active()
        self.device_service.connect_device_async(ip, dev_mode, on_connection_result)

    def _on_continue(self, button):
        """Continue to certificates page."""
        self.window.navigate_to_page(self.window.certificates_page, _("Certificates"))

    def _show_error(self, message):
        """Show error toast."""
        self.window.logger.error(message)
        ErrorNotification.show_toast(self.window, message, timeout=5)

    def _show_success(self, message):
        """Show success toast."""
        self.window.logger.info(message)
        ErrorNotification.show_toast(self.window, message, timeout=3)
