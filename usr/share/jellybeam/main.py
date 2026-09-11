# main.py
#!/usr/bin/env python3

import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from app import JellyBeamApplication


def main():
    """Entry point of the application."""
    app = JellyBeamApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    main()
