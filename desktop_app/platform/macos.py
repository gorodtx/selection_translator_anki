from __future__ import annotations

from dataclasses import dataclass

from desktop_app.platform.contracts import (
    PlatformAdapter,
    PlatformCapabilities,
    PlatformTarget,
)


@dataclass(frozen=True, slots=True)
class MacOSAdapter(PlatformAdapter):
    @property
    def target(self) -> PlatformTarget:
        return PlatformTarget.MACOS

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            global_hotkey=False,
            tray_menu=False,
            settings_entrypoint=False,
            history_entrypoint=False,
            dbus_transport=False,
            production_supported=False,
        )

    def open_settings(self) -> None:
        # macOS adapter is intentionally disabled in the current release cycle.
        return
