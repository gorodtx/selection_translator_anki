from __future__ import annotations

import importlib
import os
from collections.abc import Callable
import sys
import threading

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
from desktop_app.platform import PlatformAdapter, PlatformTarget, resolve_platform_adapter
from desktop_app.platform.windows_ipc import PipeHandlers, WindowsIpcService
from desktop_app.presentation.dbus.service import DbusService
from desktop_app.infrastructure.services.container import AppServices
from desktop_app.runtime_namespace import app_id
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


APP_ID = app_id()


class TranslatorApp(gtk_types.Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self._config = load_config()
        self._services = AppServices.create()
        self._platform: PlatformAdapter = resolve_platform_adapter()
        self._clipboard_writer = ClipboardWriter()
        self._dbus_service: DbusService | None = None
        self._windows_ipc_service: WindowsIpcService | None = None
        self._anki_controller: AnkiController | None = None
        self._settings_controller: SettingsController | None = None
        self._translation_controller: TranslationController | None = None
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _on_startup(self, _app: gtk_types.Gtk.Application) -> None:
        self.hold()
        self._services.start()
        self._build_controllers()
        self._reset_settings_if_requested()
        GLib.set_application_name("Translator")
        GLib.set_prgname("translator")
        self._register_dbus_service()
        self._register_windows_ipc_service()

    def _on_activate(self, _app: gtk_types.Gtk.Application) -> None:
        return None

    def _on_shutdown(self, _app: gtk_types.Gtk.Application) -> None:
        if self._dbus_service is not None:
            self._dbus_service.close()
            self._dbus_service = None
        if self._windows_ipc_service is not None:
            self._windows_ipc_service.close()
            self._windows_ipc_service = None
        if self._translation_controller is not None:
            self._translation_controller.cancel_tasks()
        self._services.stop()
        self.release()

    def _register_dbus_service(self) -> None:
        if not self._platform.capabilities.dbus_transport:
            return
        if not self._ensure_controllers_ready():
            return
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

    def _register_windows_ipc_service(self) -> None:
        if self._platform.target is not PlatformTarget.WINDOWS:
            return
        handlers = PipeHandlers(
            on_translate=self._on_ipc_translate,
            on_show_settings=self._on_ipc_show_settings,
            on_show_history=self._on_ipc_show_history,
            on_get_anki_status=self._on_ipc_get_anki_status,
        )
        self._windows_ipc_service = WindowsIpcService.register(handlers=handlers)

    def _on_dbus_translate(self, text: str) -> None:
        if not self._ensure_controllers_ready():
            return
        if self._translation_controller is None:
            return
        self._translation_controller.trigger_text(
            text,
            silent=True,
            prepare=False,
            hotkey=True,
            source="dbus",
        )

    def _on_ipc_translate(self, text: str) -> None:
        GLib.idle_add(self._dispatch_ipc_translate, text)

    def _dispatch_ipc_translate(self, text: str) -> bool:
        self._on_dbus_translate(text)
        return False

    def _on_dbus_get_anki_status(self, reply: Callable[[AnkiStatus], None]) -> None:
        if not self._ensure_controllers_ready():
            reply(self._fallback_anki_status())
            return
        if self._settings_controller is None:
            reply(self._fallback_anki_status())
            return
        self._settings_controller.get_anki_status(reply)

    def _on_dbus_create_model(self, reply: Callable[[AnkiActionResult], None]) -> None:
        if not self._ensure_controllers_ready():
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        if self._settings_controller is None:
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
            reply(AnkiListResult(items=[], error="Settings controller is not ready."))
            return
        if self._settings_controller is None:
            reply(AnkiListResult(items=[], error="Settings controller is not ready."))
            return
        self._settings_controller.list_decks(reply)

    def _on_dbus_select_deck(
        self, deck: str, reply: Callable[[AnkiActionResult], None]
    ) -> None:
        if not self._ensure_controllers_ready():
            del deck
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        if self._settings_controller is None:
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
            reply(
                AnkiActionResult(
                    message="Settings controller is not ready.",
                    status=self._fallback_anki_status(),
                )
            )
            return
        if self._settings_controller is None:
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
            return
        if self._translation_controller is None:
            return
        self._translation_controller.show_history_window()

    def _on_ipc_show_history(self) -> None:
        GLib.idle_add(self._dispatch_ipc_show_history)

    def _dispatch_ipc_show_history(self) -> bool:
        self._show_history()
        return False

    def _open_settings(self) -> None:
        self._platform.open_settings()

    def _on_ipc_show_settings(self) -> None:
        GLib.idle_add(self._dispatch_ipc_show_settings)

    def _dispatch_ipc_show_settings(self) -> bool:
        self._open_settings()
        return False

    def _on_ipc_get_anki_status(self) -> dict[str, str]:
        fallback = self._fallback_anki_status()
        payload = {
            "model_status": fallback.model_status,
            "deck_status": fallback.deck_status,
            "deck_name": fallback.deck_name,
        }
        if not sys.platform.startswith("win"):
            return payload
        done = threading.Event()

        def _reply(status: AnkiStatus) -> None:
            payload["model_status"] = status.model_status
            payload["deck_status"] = status.deck_status
            payload["deck_name"] = status.deck_name
            done.set()

        def _request() -> bool:
            try:
                self._on_dbus_get_anki_status(_reply)
            except Exception:
                done.set()
            return False

        GLib.idle_add(_request)
        done.wait()
        return payload

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
            return False
        return (
            self._translation_controller is not None
            and self._settings_controller is not None
            and self._anki_controller is not None
        )

    def _fallback_anki_status(self) -> AnkiStatus:
        return AnkiStatus(
            model_status="Model not found",
            deck_status="Not selected",
            deck_name="",
        )
