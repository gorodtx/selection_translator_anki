from __future__ import annotations

import importlib
import logging
import os
import time
from collections.abc import Callable

from desktop_app.infrastructure.adapters.clipboard_writer import ClipboardWriter
from desktop_app.infrastructure.anki import AnkiListResult
from desktop_app.config import AppConfig, config_path, load_config, save_config
from desktop_app.presentation.controllers import (
    AnkiController,
    SettingsController,
    TranslationController,
)
from desktop_app.presentation.controllers.settings_controller import (
    AnkiActionResult,
    AnkiStatus,
)
from desktop_app.application.use_cases.translation_executor import TranslationExecutor
from desktop_app.presentation.dbus.service import DbusService
from desktop_app.infrastructure.services.container import AppServices
from desktop_app import gtk_types

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gio", "2.0")
    require_version("GLib", "2.0")
    require_version("Gtk", "4.0")
GLib = importlib.import_module("gi.repository.GLib")
Gtk = importlib.import_module("gi.repository.Gtk")
setattr(gtk_types.Gtk, "Application", getattr(Gtk, "Application"))


APP_ID = "com.translator.desktop"
logger = logging.getLogger(__name__)


class TranslatorApp(gtk_types.Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self._config = load_config()
        self._services = AppServices.create()
        self._clipboard_writer = ClipboardWriter()
        self._dbus_service: DbusService | None = None
        self._anki_controller: AnkiController | None = None
        self._settings_controller: SettingsController | None = None
        self._translation_controller: TranslationController | None = None
        self._startup_retry_source_id: int | None = None
        self._startup_retry_attempts: int = 0
        self._startup_started_at: float = 0.0
        self._startup_ready_timeout_seconds: float = _startup_ready_timeout()
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _on_startup(self, _app: gtk_types.Gtk.Application) -> None:
        self.hold()
        self._startup_retry_attempts = 0
        self._startup_started_at = time.monotonic()
        self._services.start()
        self._reset_settings_if_requested()
        GLib.set_application_name("Translator")
        GLib.set_prgname("translator")
        if not self._initialize_startup_components():
            self._schedule_startup_retry()

    def _on_activate(self, _app: gtk_types.Gtk.Application) -> None:
        return None

    def _on_shutdown(self, _app: gtk_types.Gtk.Application) -> None:
        if self._startup_retry_source_id is not None:
            try:
                GLib.source_remove(self._startup_retry_source_id)
            except Exception:
                pass
            self._startup_retry_source_id = None
        if self._dbus_service is not None:
            self._dbus_service.close()
            self._dbus_service = None
        if self._translation_controller is not None:
            self._translation_controller.cancel_tasks()
        self._services.stop()
        self.release()

    def _register_dbus_service(self) -> None:
        if self._dbus_service is not None:
            return
        if not self._ensure_controllers_ready():
            return
        try:
            self._dbus_service = DbusService.register(
                app=self,
                on_translate=self._on_dbus_translate,
                on_show_settings=self._open_settings,
                on_show_history=self._show_history,
                on_get_anki_status=self._on_dbus_get_anki_status,
                on_create_model=self._on_dbus_create_model,
                on_list_decks=self._on_dbus_list_decks,
                on_select_deck=self._on_dbus_select_deck,
                on_save_settings=self._on_dbus_save_settings,
            )
        except Exception:
            logger.exception("failed to register D-Bus service")
            self._dbus_service = None

    def _initialize_startup_components(self) -> bool:
        if not self._ensure_controllers_ready():
            return False
        self._register_dbus_service()
        return self._dbus_service is not None

    def _schedule_startup_retry(self) -> None:
        if self._startup_retry_source_id is not None:
            return
        self._startup_retry_source_id = GLib.timeout_add(
            1000, self._retry_startup_components
        )

    def _retry_startup_components(self) -> bool:
        if self._initialize_startup_components():
            self._startup_retry_source_id = None
            return False
        self._startup_retry_attempts += 1
        if self._startup_retry_attempts % 5 == 0:
            logger.warning(
                "startup components are still not ready (attempt=%s, elapsed=%.1fs)",
                self._startup_retry_attempts,
                max(time.monotonic() - self._startup_started_at, 0.0),
            )
        if self._startup_retry_expired():
            logger.critical(
                "startup readiness timeout exceeded (%.1fs), forcing restart",
                self._startup_ready_timeout_seconds,
            )
            self._force_restart()
            return False
        return True

    def _on_dbus_translate(self, text: str) -> None:
        if not self._ensure_controllers_ready():
            self._maybe_force_restart_on_unready()
            return
        if self._translation_controller is None:
            self._maybe_force_restart_on_unready()
            return
        self._translation_controller.trigger_text(
            text,
            silent=True,
            prepare=False,
            hotkey=True,
            source="dbus",
        )

    def _on_dbus_get_anki_status(self, reply: Callable[[AnkiStatus], None]) -> None:
        if not self._ensure_controllers_ready():
            self._maybe_force_restart_on_unready()
            reply(self._fallback_anki_status())
            return
        if self._settings_controller is None:
            self._maybe_force_restart_on_unready()
            reply(self._fallback_anki_status())
            return
        self._settings_controller.get_anki_status(reply)

    def _on_dbus_create_model(self, reply: Callable[[AnkiActionResult], None]) -> None:
        if not self._ensure_controllers_ready():
            self._maybe_force_restart_on_unready()
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        if self._settings_controller is None:
            self._maybe_force_restart_on_unready()
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        self._settings_controller.create_model(reply)

    def _on_dbus_list_decks(self, reply: Callable[[AnkiListResult], None]) -> None:
        if not self._ensure_controllers_ready():
            self._maybe_force_restart_on_unready()
            reply(AnkiListResult(items=[], error="Settings controller is not ready."))
            return
        if self._settings_controller is None:
            self._maybe_force_restart_on_unready()
            reply(AnkiListResult(items=[], error="Settings controller is not ready."))
            return
        self._settings_controller.list_decks(reply)

    def _on_dbus_select_deck(
        self, deck: str, reply: Callable[[AnkiActionResult], None]
    ) -> None:
        if not self._ensure_controllers_ready():
            self._maybe_force_restart_on_unready()
            del deck
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        if self._settings_controller is None:
            self._maybe_force_restart_on_unready()
            del deck
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        self._settings_controller.select_deck(deck, reply)

    def _on_dbus_save_settings(self, reply: Callable[[AnkiActionResult], None]) -> None:
        if not self._ensure_controllers_ready():
            self._maybe_force_restart_on_unready()
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        if self._settings_controller is None:
            self._maybe_force_restart_on_unready()
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        self._settings_controller.save_settings(reply)

    def _show_history(self) -> None:
        if not self._ensure_controllers_ready():
            self._maybe_force_restart_on_unready()
            return
        if self._translation_controller is None:
            self._maybe_force_restart_on_unready()
            return
        self._translation_controller.show_history_window()

    def _open_settings(self) -> None:
        return None

    def _on_settings_saved(self, config: AppConfig) -> None:
        self._config = config
        save_config(config)
        if self._translation_controller is not None:
            self._translation_controller.update_config(self._config)
        if self._settings_controller is not None:
            self._settings_controller.update_config(self._config)

    def _on_present_window(self, window: gtk_types.Gtk.ApplicationWindow) -> None:
        del window

    def _reset_settings_if_requested(self) -> None:
        if os.environ.get("TRANSLATOR_RESET", "").strip() != "1":
            return
        try:
            path = config_path()
            if path.exists():
                path.unlink()
        except OSError:
            pass
        self._config = load_config()
        if self._translation_controller is not None:
            self._translation_controller.update_config(self._config)

    def _build_controllers(self) -> None:
        if self._anki_controller is None:
            self._anki_controller = AnkiController(anki_flow=self._services.anki_flow)
        if self._settings_controller is None:
            self._settings_controller = SettingsController(
                config=self._config,
                runtime=self._services.runtime,
                anki_flow=self._services.anki_flow,
                on_save=self._on_settings_saved,
            )
        if self._translation_controller is None:
            self._translation_controller = TranslationController(
                app=self,
                translation_executor=TranslationExecutor(
                    flow=self._services.translation_flow,
                    config=self._config,
                ),
                cancel_active=self._services.cancel_active,
                config=self._config,
                clipboard_writer=self._clipboard_writer,
                anki_controller=self._anki_controller,
                on_present_window=self._on_present_window,
                on_open_settings=self._open_settings,
            )

    def _ensure_controllers_ready(self) -> bool:
        if (
            self._translation_controller is not None
            and self._settings_controller is not None
            and self._anki_controller is not None
        ):
            return True
        try:
            self._build_controllers()
        except Exception:
            logger.exception("failed to initialize controllers")
            return False
        return (
            self._translation_controller is not None
            and self._settings_controller is not None
            and self._anki_controller is not None
        )

    def _startup_retry_expired(self) -> bool:
        if self._startup_started_at <= 0:
            return False
        return (
            time.monotonic() - self._startup_started_at
        ) >= self._startup_ready_timeout_seconds

    def _maybe_force_restart_on_unready(self) -> None:
        self._schedule_startup_retry()
        if self._startup_retry_expired():
            logger.critical(
                "controllers are still unavailable after %.1fs, forcing restart",
                self._startup_ready_timeout_seconds,
            )
            self._force_restart()

    def _force_restart(self) -> None:
        os._exit(1)

    def _fallback_anki_status(self) -> AnkiStatus:
        return AnkiStatus(
            model_status="Model not found",
            deck_status="Not selected",
            deck_name="",
        )


def _startup_ready_timeout() -> float:
    value = os.environ.get("TRANSLATOR_STARTUP_READY_TIMEOUT_SECONDS", "45")
    try:
        timeout = float(value)
    except ValueError:
        return 45.0
    if timeout < 5:
        return 5.0
    return timeout
