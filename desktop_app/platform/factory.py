from __future__ import annotations

import os
import sys

from desktop_app.platform.contracts import PlatformAdapter
from desktop_app.platform.linux_gnome import LinuxGnomeAdapter
from desktop_app.platform.macos import MacOSAdapter
from desktop_app.platform.other import OtherPlatformAdapter
from desktop_app.platform.windows import WindowsAdapter


def resolve_platform_adapter() -> PlatformAdapter:
    if sys.platform.startswith("linux"):
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").casefold()
        is_gnome = "gnome" in desktop
        if is_gnome:
            return LinuxGnomeAdapter()
        return OtherPlatformAdapter()

    if sys.platform.startswith("win"):
        return WindowsAdapter()

    if sys.platform == "darwin":
        return MacOSAdapter()

    return OtherPlatformAdapter()
