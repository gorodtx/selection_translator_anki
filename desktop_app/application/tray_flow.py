from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desktop_app.adapters.tray import TrayManager


@dataclass(slots=True)
class TrayFlow:
    manager: TrayManager

    def start(self, icon_path: Path) -> None:
        self.manager.start(icon_path)

    def stop(self) -> None:
        self.manager.stop()
