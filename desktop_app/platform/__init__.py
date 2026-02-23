from __future__ import annotations

from desktop_app.platform.contracts import (
    PlatformAdapter as PlatformAdapter,
    PlatformCapabilities as PlatformCapabilities,
    PlatformTarget as PlatformTarget,
)
from desktop_app.platform.factory import (
    resolve_platform_adapter as resolve_platform_adapter,
)
from desktop_app.platform.linux_gnome import LinuxGnomeAdapter as LinuxGnomeAdapter
from desktop_app.platform.macos import MacOSAdapter as MacOSAdapter
from desktop_app.platform.other import OtherPlatformAdapter as OtherPlatformAdapter
from desktop_app.platform.windows import WindowsAdapter as WindowsAdapter

__all__ = [
    "PlatformAdapter",
    "PlatformCapabilities",
    "PlatformTarget",
    "LinuxGnomeAdapter",
    "WindowsAdapter",
    "MacOSAdapter",
    "OtherPlatformAdapter",
    "resolve_platform_adapter",
]
