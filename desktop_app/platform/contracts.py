from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class PlatformTarget(str, Enum):
    LINUX_GNOME = "linux-gnome"
    WINDOWS = "windows"
    MACOS = "macos"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    global_hotkey: bool
    tray_menu: bool
    settings_entrypoint: bool
    history_entrypoint: bool
    dbus_transport: bool
    production_supported: bool


class PlatformAdapter(Protocol):
    @property
    def target(self) -> PlatformTarget: ...

    @property
    def capabilities(self) -> PlatformCapabilities: ...

    def open_settings(self) -> None: ...
