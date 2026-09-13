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
    try:
        return app.run(sys.argv)
    except KeyboardInterrupt:
        # Ctrl+C in the terminal is a normal way to close the app; it used to
        # end in a traceback, which reads like a crash to whoever sees it.
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
