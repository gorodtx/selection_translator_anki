from __future__ import annotations

from dataclasses import dataclass

from desktop_app.config import AppConfig


@dataclass(slots=True)
class AutostartFlow:
    def update_config(self, config: AppConfig, enabled: bool) -> AppConfig:
        return AppConfig(
            languages=config.languages,
            anki=config.anki,
            hotkey=config.hotkey,
            autostart_prompted=True,
            autostart_enabled=enabled,
            ready_notified=config.ready_notified,
        )
