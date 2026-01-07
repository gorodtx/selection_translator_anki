from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desktop_app.adapters.desktop_entry import DesktopEntryManager


@dataclass(slots=True)
class DesktopEntryFlow:
    manager: DesktopEntryManager

    def ensure_shortcut(self, icon_path: Path) -> None:
        self.manager.ensure_app_shortcut(icon_path)

    def ensure_autostart(self, icon_path: Path) -> None:
        self.manager.ensure_autostart(icon_path)

    def autostart_entry_path(self) -> Path:
        return self.manager.autostart_entry_path()

    def cleanup_entries(self) -> None:
        self.manager.cleanup_desktop_entries()

    def cleanup_cache(self) -> None:
        self.manager.cleanup_desktop_cache()
