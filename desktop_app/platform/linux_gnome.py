from __future__ import annotations

from dataclasses import dataclass

from desktop_app.platform.contracts import (
    PlatformAdapter,
    PlatformCapabilities,
    PlatformTarget,
)


@dataclass(frozen=True, slots=True)
class LinuxGnomeAdapter(PlatformAdapter):
    @property
    def target(self) -> PlatformTarget:
        return PlatformTarget.LINUX_GNOME

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            global_hotkey=True,
            tray_menu=True,
            settings_entrypoint=True,
            history_entrypoint=True,
            dbus_transport=True,
            production_supported=True,
        )

    def open_settings(self) -> None:
        # GNOME extension preferences own settings UI entrypoint.
        return
