# app.py
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio
from pages.welcome import WelcomePage
from pages.device import DevicePage
from pages.certificates import CertificatesPage
from pages.install import InstallPage
from pages.preferences import PreferencesPage
from utils.config import ConfigManager
from utils import design
from utils.logger import Logger
from utils.constants import (
    APP_ID,
    APP_NAME,
    APP_VERSION,
    APP_GITHUB_URL,
    APP_ISSUE_URL,
    APP_COPYRIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_MIN_HEIGHT,
)
from utils.i18n import _
from services.docker import DockerService
from services.device import DeviceService
from services.certificates import CertificateService


class JellyBeamApplication(Adw.Application):
    """Main application class for JellyBeam."""

    def __init__(self):
        super().__init__(
            application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

        self.config_manager = ConfigManager()
        self.logger = Logger()
        self.logger.info(f"{APP_NAME} {APP_VERSION} starting")
        self.window = None

    def do_activate(self):
        """Called when the application is activated."""
        # After the display exists, before any page is built.
        design.load_css()
        if not self.window:
            self.window = JellyBeamWindow(
                application=self, config_manager=self.config_manager, logger=self.logger
            )
        self.window.present()


class JellyBeamWindow(Adw.ApplicationWindow):
    """Main application window."""

    def __init__(self, application, config_manager, logger):
        super().__init__(application=application)

        self.config_manager = config_manager
        self.logger = logger

        # Initialize services with logger
        self.docker_service = DockerService(logger=logger)
        self.device_service = DeviceService(logger=logger)
        self.certificate_service = CertificateService(logger=logger)

        self.logger.info("Initializing main window")

        self.set_title(APP_NAME)

        # Set window size from constants
        self.set_default_size(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)

        # Set minimum size
        self.set_resizable(True)
        self.set_size_request(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self._setup_ui()
        self._setup_actions()

    def _setup_ui(self):
        """Setup the main UI components."""
        # Main content
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.content_box)

        # Header bar — flat style blends with background
        self.header_bar = Adw.HeaderBar()
        self.header_bar.add_css_class("flat")
        self.content_box.append(self.header_bar)

        # Back button (initially hidden)
        self.back_button = Gtk.Button()
        self.back_button.set_icon_name("go-previous-symbolic")
        self.back_button.set_tooltip_text(_("Go Back"))
        self.back_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Go Back")])
        self.back_button.set_visible(False)
        self.back_button.connect("clicked", self._on_back_clicked)
        self.header_bar.pack_start(self.back_button)

        # Menu button
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_icon_name("open-menu-symbolic")
        self.menu_button.set_menu_model(self._create_menu())
        self.menu_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Main Menu")]
        )
        self.header_bar.pack_end(self.menu_button)

        # Reusable title label for header bar
        self._title_label = Gtk.Label()
        self.header_bar.set_title_widget(self._title_label)

        # Toast overlay for notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_vexpand(True)
        self.content_box.append(self.toast_overlay)

        # Navigation view with scroll control
        self.navigation_view = Adw.NavigationView()
        self.navigation_view.set_vexpand(True)  # Fill available space
        self.navigation_view.connect("notify::visible-page", self._on_page_changed)
        self.toast_overlay.set_child(self.navigation_view)

        # Pages
        self.welcome_page = WelcomePage(self)
        self.device_page = DevicePage(self)
        self.certificates_page = CertificatesPage(self)
        self.install_page = InstallPage(self)

        # Add welcome page initially (no title in header bar)
        nav_page = Adw.NavigationPage(child=self.welcome_page, title="", tag="welcome")
        self.navigation_view.add(nav_page)

    def _on_page_changed(self, nav_view, param):
        """Update back button visibility when page changes."""
        # Show back button if we can go back (not on first page)
        can_go_back = (
            nav_view.get_previous_page(nav_view.get_visible_page()) is not None
        )
        self.back_button.set_visible(can_go_back)

        # Update header title
        visible_page = nav_view.get_visible_page()
        if visible_page:
            self._title_label.set_label(visible_page.get_title())

    def _on_back_clicked(self, button):
        """Handle back button click."""
        self.navigation_view.pop()

    def _create_menu(self):
        """Create the main application menu."""
        menu = Gio.Menu()
        menu.append(_("Preferences"), "win.preferences")
        menu.append(_("About"), "win.about")
        return menu

    def _setup_actions(self):
        """Setup application actions."""
        # Preferences action
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self._on_preferences)
        self.add_action(preferences_action)

        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def _on_preferences(self, action, param):
        """Show preferences window."""
        preferences_window = PreferencesPage(self)
        preferences_window.present(self)

    def _on_about(self, action, param):
        """Show about dialog."""
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon="jellybeam",
            version=APP_VERSION,
            developer_name=_("JellyBeam Team"),
            license_type=Gtk.License.GPL_3_0,
            website=APP_GITHUB_URL,
            issue_url=APP_ISSUE_URL,
            copyright=APP_COPYRIGHT,
        )
        about.set_developers([_("JellyBeam Contributors")])
        about.present(self)

    def navigate_to_page(self, page_widget, title):
        """Navigate to a specific page."""
        nav_page = Adw.NavigationPage(child=page_widget, title=title)
        self.navigation_view.push(nav_page)
