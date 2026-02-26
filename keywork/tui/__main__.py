"""Entry point for the Keywork TUI."""

from keywork.tui.app import KeyworkTUI


def main():
    app = KeyworkTUI()
    app.run()


if __name__ == "__main__":
    main()
