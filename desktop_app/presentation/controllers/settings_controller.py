from __future__ import annotations

from collections.abc import Callable
import importlib

from desktop_app.application.anki_status import AnkiActionResult as AnkiActionResult
from desktop_app.application.anki_status import AnkiStatus as AnkiStatus
from desktop_app.application.use_cases.anki_flow import AnkiFlow
from desktop_app.application.use_cases.settings_flow import SettingsFlow
from desktop_app.config import AppConfig
from desktop_app.infrastructure.services.runtime import AsyncRuntime

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("GLib", "2.0")
GLib = importlib.import_module("gi.repository.GLib")


def _run_once(callback: Callable[[], None]) -> bool:
    callback()
    return False


def glib_dispatch(callback: Callable[[], None]) -> None:
    GLib.idle_add(_run_once, callback)


class SettingsController(SettingsFlow):
    def __init__(
        self,
        *,
        config: AppConfig,
        runtime: AsyncRuntime,
        anki_flow: AnkiFlow,
        on_save: Callable[[AppConfig], None],
    ) -> None:
        super().__init__(
            config=config,
            runtime=runtime,
            anki_flow=anki_flow,
            on_save=on_save,
            dispatch=glib_dispatch,
        )
