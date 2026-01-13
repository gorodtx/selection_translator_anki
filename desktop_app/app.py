from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Callable

from desktop_app.adapters.clipboard_writer import ClipboardWriter
from desktop_app.anki import AnkiListResult
from desktop_app.config import AppConfig, config_path, load_config, save_config
from desktop_app.controllers import (
    AnkiController,
    SettingsController,
    TranslationController,
)
from desktop_app.controllers.settings_controller import AnkiActionResult, AnkiStatus
from desktop_app.gnome.dbus_service import DbusService
from desktop_app.services.container import AppServices
from desktop_app.settings import SettingsWindow
from desktop_app import gtk_types
from desktop_app import telemetry

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


class TranslatorApp(gtk_types.Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        logging.getLogger().setLevel(logging.ERROR)
        self._config = load_config()
        self._services = AppServices.create()
        self._clipboard_writer = ClipboardWriter()
        self._settings_window: SettingsWindow | None = None
        self._dbus_service: DbusService | None = None
        self._anki_controller = AnkiController(anki_flow=self._services.anki_flow)
        self._settings_controller = SettingsController(
            config=self._config,
            runtime=self._services.runtime,
            anki_flow=self._services.anki_flow,
            on_save=self._on_settings_saved,
        )
        self._translation_controller = TranslationController(
            app=self,
            translation_flow=self._services.translation_flow,
            cancel_active=self._services.cancel_active,
            config=self._config,
            clipboard_writer=self._clipboard_writer,
            anki_controller=self._anki_controller,
            selection_cache=self._services.selection_cache,
            on_present_window=self._on_present_window,
            on_open_settings=self._open_settings,
        )
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _on_startup(self, _app: gtk_types.Gtk.Application) -> None:
        telemetry.setup(reset=True)
        telemetry.log_event("app.start", app_id=APP_ID)
        self.hold()
        self._services.start()
        self._reset_settings_if_requested()
        GLib.set_application_name("Translator")
        GLib.set_prgname("translator")
        self._register_dbus_service()
        self._anki_controller.refresh_decks(
            update_availability=False,
            set_anki_available=self._translation_controller.set_anki_available,
        )

    def _on_activate(self, _app: gtk_types.Gtk.Application) -> None:
        telemetry.log_event("app.activate")

    def _on_shutdown(self, _app: gtk_types.Gtk.Application) -> None:
        if self._dbus_service is not None:
            self._dbus_service.close()
            self._dbus_service = None
        self._translation_controller.cancel_tasks()
        self._services.stop()
        telemetry.log_event("app.shutdown")
        telemetry.shutdown()
        self.release()

    def _register_dbus_service(self) -> None:
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

    def _on_dbus_translate(self, text: str) -> None:
        telemetry.log_event("dbus.translate", **telemetry.text_meta(text))
        self._translation_controller.trigger_text(
            text,
            silent=True,
            prepare=False,
            hotkey=True,
            source="dbus",
        )

    def _on_dbus_get_anki_status(self, reply: Callable[[AnkiStatus], None]) -> None:
        self._settings_controller.get_anki_status(reply)

    def _on_dbus_create_model(self, reply: Callable[[AnkiActionResult], None]) -> None:
        self._settings_controller.create_model(reply)

    def _on_dbus_list_decks(self, reply: Callable[[AnkiListResult], None]) -> None:
        self._settings_controller.list_decks(reply)

    def _on_dbus_select_deck(
        self, deck: str, reply: Callable[[AnkiActionResult], None]
    ) -> None:
        self._settings_controller.select_deck(deck, reply)

    def _on_dbus_save_settings(self, reply: Callable[[AnkiActionResult], None]) -> None:
        self._settings_controller.save_settings(reply)

    def _show_history(self) -> None:
        self._translation_controller.show_history_window()

    def _open_settings(self) -> None:
        if os.environ.get("TRANSLATOR_ENABLE_PY_SETTINGS", "").strip() != "1":
            telemetry.log_event("settings.python.disabled")
            return
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                app=self,
                config=self._config,
                runtime=self._services.runtime,
                anki_flow=self._services.anki_flow,
                on_save=self._on_settings_saved,
            )
        else:
            self._settings_window.update_config(self._config)
        self._settings_window.present()
        self._on_present_window(self._settings_window.window)

    def _on_settings_saved(self, config: AppConfig) -> None:
        self._config = config
        save_config(config)
        self._translation_controller.update_config(self._config)
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
        self._services.selection_cache.clear()
        self._config = load_config()
        self._translation_controller.update_config(self._config)
