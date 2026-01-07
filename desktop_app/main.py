from __future__ import annotations

import sys

from desktop_app.app import TranslatorApp


def main() -> None:
    app = TranslatorApp()
    app._ensure_app_shortcut()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
