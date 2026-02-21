from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
import importlib
from pathlib import Path

from desktop_app.infrastructure.anki import AnkiCreateModelResult, AnkiListResult
from desktop_app.infrastructure.anki.importer import DeckImportResult, import_deck
from desktop_app.infrastructure.anki.templates import (
    DEFAULT_BACK_TEMPLATE,
    DEFAULT_FRONT_TEMPLATE,
    DEFAULT_MODEL_CSS,
    DEFAULT_MODEL_FIELDS,
    DEFAULT_MODEL_NAME,
)
from desktop_app.application.use_cases.anki_flow import AnkiFlow
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig
from desktop_app.infrastructure.notifications import BannerHost, Notification
from desktop_app.infrastructure.notifications import messages as notify_messages
from desktop_app.infrastructure.services.runtime import AsyncRuntime
from desktop_app import gtk_types

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gdk", "4.0")
    require_version("Gio", "2.0")
    require_version("GLib", "2.0")
    require_version("Gtk", "4.0")
Gdk = importlib.import_module("gi.repository.Gdk")
Gio = importlib.import_module("gi.repository.Gio")
GLib = importlib.import_module("gi.repository.GLib")
Gtk = importlib.import_module("gi.repository.Gtk")


class SettingsWindow:
    def __init__(
        self,
        app: gtk_types.Gtk.Application,
        config: AppConfig,
        runtime: AsyncRuntime,
        anki_flow: AnkiFlow,
        on_save: Callable[[AppConfig], None],
    ) -> None:
        self._app = app
        self._config = config
        self._runtime = runtime
        self._anki_flow = anki_flow
        self._on_save = on_save
        self._import_future: Future[DeckImportResult] | None = None
        self._create_model_future: Future[AnkiCreateModelResult] | None = None
        self._model_names_future: Future[AnkiListResult] | None = None
        self._model_ready = False
        self._pending_anki: AnkiConfig | None = None
        self._window = Gtk.ApplicationWindow(application=app)
        self._window.set_title("Settings")
        self._window.set_default_size(460, 360)
        self._window.set_resizable(False)
        self._window.set_hide_on_close(True)
        self._window.set_decorated(False)
        self._window.connect("close-request", self._on_close_request)

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self._window.add_controller(controller)

        self._import_button = Gtk.Button(label="Import Deck")
        self._create_model_button = Gtk.Button(label="Create Model")
        self._model_status_label = Gtk.Label(label="Model status: unknown")
        self._deck_status_label = Gtk.Label(label="Deck status: not selected")
        self._banner = BannerHost()

        self._build_layout()
        self._apply_config(config)

    def present(self) -> None:
        self._window.present()

    @property
    def window(self) -> gtk_types.Gtk.ApplicationWindow:
        return self._window

    def update_config(self, config: AppConfig) -> None:
        self._config = config
        self._apply_config(config)

    def _build_layout(self) -> None:
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        container.set_margin_top(12)
        container.set_margin_bottom(12)
        container.set_margin_start(12)
        container.set_margin_end(12)
        container.append(self._banner.widget)

        anki_title = Gtk.Label(label="Anki")
        anki_title.set_xalign(0.5)
        anki_title.set_hexpand(True)
        container.append(anki_title)

        self._import_button.connect("clicked", self._on_import_clicked)
        container.append(self._import_button)

        self._create_model_button.connect("clicked", self._on_create_model_clicked)
        container.append(self._create_model_button)

        self._model_status_label.set_xalign(0.0)
        self._model_status_label.set_wrap(True)
        self._model_status_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        container.append(self._model_status_label)

        self._deck_status_label.set_xalign(0.0)
        self._deck_status_label.set_wrap(True)
        self._deck_status_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        container.append(self._deck_status_label)

        save_button = Gtk.Button(label="Save Settings")
        save_button.connect("clicked", self._on_save_clicked)
        container.append(save_button)

        self._attach_window_drag(container)
        self._window.set_child(container)

    def _attach_window_drag(self, widget: gtk_types.Gtk.Widget) -> None:
        gesture = Gtk.GestureDrag()
        gesture.set_button(1)
        gesture.connect("drag-begin", self._on_drag_begin)
        widget.add_controller(gesture)

    def _on_drag_begin(
        self, gesture: gtk_types.Gtk.GestureDrag, x: float, y: float
    ) -> None:
        if self._is_interactive_target(x, y):
            return
        surface = self._window.get_surface()
        if surface is None:
            return
        device = gesture.get_current_event_device()
        if device is None:
            return
        timestamp = gesture.get_current_event_time()
        button = gesture.get_current_button()
        if hasattr(surface, "begin_move"):
            surface.begin_move(device, button, x, y, timestamp)

    def _is_interactive_target(self, x: float, y: float) -> bool:
        target = self._window.pick(x, y, 0)
        while target is not None:
            if isinstance(target, Gtk.Button):
                return True
            target = target.get_parent()
        return False

    def _apply_config(self, config: AppConfig) -> None:
        self._pending_anki = config.anki
        self._update_deck_status(config.anki.deck)
        self._refresh_model_status()

    def _on_close_request(self, window: gtk_types.Gtk.ApplicationWindow) -> bool:
        window.hide()
        return True

    def _on_key_pressed(
        self,
        _controller: gtk_types.Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: int,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._window.hide()
            return True
        return False

    def _on_save_clicked(self, _button: gtk_types.Gtk.Button) -> None:
        anki_config = self._pending_anki or self._config.anki
        new_config = AppConfig(
            languages=self._config.languages,
            anki=anki_config,
        )
        self._on_save(new_config)
        self._notify(notify_messages.settings_saved())
        self._window.hide()

    def _on_import_clicked(self, _button: gtk_types.Gtk.Button) -> None:
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog()
            dialog.set_title("Import Anki Deck")
            dialog.open(self._window, None, self._on_import_dialog_done)
            return
        if not hasattr(Gtk, "FileChooserNative"):
            self._notify(
                notify_messages.settings_error("File picker is not available.")
            )
            return
        native_dialog = Gtk.FileChooserNative.new(
            "Import Anki Deck",
            self._window,
            Gtk.FileChooserAction.OPEN,
            "Open",
            "Cancel",
        )
        native_dialog.connect("response", self._on_import_native_response)
        native_dialog.show()

    def _on_create_model_clicked(self, _button: gtk_types.Gtk.Button) -> None:
        if (
            self._create_model_future is not None
            and not self._create_model_future.done()
        ):
            return
        if self._model_names_future is not None and not self._model_names_future.done():
            return
        if self._model_ready:
            self._notify(notify_messages.anki_model_exists(DEFAULT_MODEL_NAME))
            return
        try:
            self._model_names_future = self._anki_flow.model_names()
        except Exception:
            self._notify(notify_messages.settings_error("Failed to check Anki models."))
            return
        self._model_names_future.add_done_callback(
            lambda done: gtk_types.GLib.idle_add(self._on_model_names_ready, done)
        )

    def _on_model_names_ready(self, future: Future[AnkiListResult]) -> bool:
        if future.cancelled():
            return False
        try:
            result = future.result()
        except Exception:
            self._notify(notify_messages.settings_error("Failed to check Anki models."))
            return False
        if result.error is not None:
            self._notify(notify_messages.settings_error(result.error))
            return False
        deck = self._current_deck()
        if DEFAULT_MODEL_NAME in result.items:
            self._apply_created_model(deck)
            self._notify(notify_messages.anki_model_exists(DEFAULT_MODEL_NAME))
            return False
        self._start_create_model(deck)
        return False

    def _current_deck(self) -> str:
        if self._pending_anki is not None and self._pending_anki.deck:
            return self._pending_anki.deck
        return self._config.anki.deck

    def _on_import_dialog_done(
        self, dialog: gtk_types.Gtk.FileDialog, result: gtk_types.Gio.AsyncResult
    ) -> None:
        try:
            file = dialog.open_finish(result)
        except Exception:
            return
        if file is None:
            return
        path_str = file.get_path()
        if path_str is None:
            self._notify(notify_messages.settings_error("Deck path is not available."))
            return
        self._start_import(Path(path_str))

    def _on_import_native_response(
        self, dialog: gtk_types.Gtk.FileChooserNative, response: int
    ) -> None:
        try:
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file is None:
                    self._notify(
                        notify_messages.settings_error("Deck path is not available.")
                    )
                    return
                path_str = file.get_path()
                if path_str is None:
                    self._notify(
                        notify_messages.settings_error("Deck path is not available.")
                    )
                    return
                self._start_import(Path(path_str))
        finally:
            dialog.destroy()

    def _start_import(self, path: Path) -> None:
        if self._import_future is not None and not self._import_future.done():
            return
        self._import_future = asyncio.run_coroutine_threadsafe(
            self._import_deck_async(path),
            self._runtime.loop,
        )
        self._import_future.add_done_callback(self._on_import_done)

    async def _import_deck_async(self, path: Path) -> DeckImportResult:
        return await asyncio.to_thread(import_deck, path)

    def _on_import_done(self, future: Future[DeckImportResult]) -> None:
        GLib.idle_add(self._apply_import_result, future)

    def _apply_import_result(self, future: Future[DeckImportResult]) -> bool:
        if future.cancelled():
            return False
        try:
            result = future.result()
        except Exception:
            self._notify(notify_messages.settings_error("Failed to import deck."))
            return False
        if result.error is not None:
            self._notify(notify_messages.settings_error(result.error))
            return False
        if self._model_ready:
            fields = AnkiFieldMap(
                word="word",
                translation="translation",
                example_en="example_en",
                definitions_en="definitions_en",
                image="image",
            )
            model = DEFAULT_MODEL_NAME
        else:
            fields = AnkiFieldMap(
                word="",
                translation="",
                example_en="",
                definitions_en="",
                image="",
            )
            model = ""
        self._pending_anki = AnkiConfig(
            deck=result.deck,
            model=model,
            fields=fields,
        )
        self._persist_anki(self._pending_anki)
        self._update_deck_status(result.deck)
        if result.deck:
            self._notify(notify_messages.anki_deck_selected(result.deck))
        else:
            self._notify(notify_messages.anki_deck_missing())
        return False

    def _start_create_model(self, deck: str) -> None:
        if (
            self._create_model_future is not None
            and not self._create_model_future.done()
        ):
            return
        self._create_model_future = self._anki_flow.create_model(
            DEFAULT_MODEL_NAME,
            DEFAULT_MODEL_FIELDS,
            DEFAULT_FRONT_TEMPLATE,
            DEFAULT_BACK_TEMPLATE,
            DEFAULT_MODEL_CSS,
        )
        self._create_model_future.add_done_callback(
            lambda done: gtk_types.GLib.idle_add(self._on_create_model_done, done, deck)
        )

    def _on_create_model_done(
        self,
        future: Future[AnkiCreateModelResult],
        deck: str,
    ) -> bool:
        if future.cancelled():
            return False
        try:
            result = future.result()
        except Exception:
            self._notify(notify_messages.settings_error("Failed to create Anki model."))
            return False
        if result.error is not None:
            if _model_exists_error(result.error):
                self._apply_created_model(deck)
                self._notify(notify_messages.anki_model_exists(DEFAULT_MODEL_NAME))
                return False
            self._notify(notify_messages.settings_error(result.error))
            return False
        self._apply_created_model(deck)
        self._notify(notify_messages.model_created(DEFAULT_MODEL_NAME))
        return False

    def _apply_created_model(self, deck: str) -> None:
        self._model_ready = True
        self._update_model_status("ready")
        target_deck = deck or self._current_deck()
        fields = AnkiFieldMap(
            word="word",
            translation="translation",
            example_en="example_en",
            definitions_en="definitions_en",
            image="image",
        )
        self._pending_anki = AnkiConfig(
            deck=target_deck,
            model=DEFAULT_MODEL_NAME,
            fields=fields,
        )
        self._persist_anki(self._pending_anki)
        if target_deck:
            self._update_deck_status(target_deck)

    def _notify(self, notification: Notification) -> None:
        self._banner.notify(notification)

    def _persist_anki(self, anki_config: AnkiConfig) -> None:
        new_config = AppConfig(
            languages=self._config.languages,
            anki=anki_config,
        )
        self._config = new_config
        self._on_save(new_config)

    def _refresh_model_status(self) -> None:
        if self._model_names_future is not None and not self._model_names_future.done():
            return
        try:
            self._model_names_future = self._anki_flow.model_names()
        except Exception:
            self._model_ready = False
            self._update_model_status("not_found")
            return
        self._model_names_future.add_done_callback(
            lambda done: gtk_types.GLib.idle_add(self._on_model_status_ready, done)
        )

    def _on_model_status_ready(self, future: Future[AnkiListResult]) -> bool:
        if future.cancelled():
            return False
        try:
            result = future.result()
        except Exception:
            self._model_ready = False
            self._update_model_status("not_found")
            return False
        if result.error is not None:
            self._model_ready = False
            self._update_model_status("not_found")
            return False
        self._model_ready = DEFAULT_MODEL_NAME in result.items
        self._update_model_status("ready" if self._model_ready else "not_found")
        if self._model_ready and self._config.anki.model != DEFAULT_MODEL_NAME:
            self._apply_created_model(self._current_deck())
        return False

    def _update_model_status(self, status: str) -> None:
        if status == "ready":
            text = "Model status: ready"
        elif status == "not_found":
            text = "Model status: not found"
        else:
            text = "Model status: unknown"
        self._model_status_label.set_text(text)

    def _update_deck_status(self, deck: str) -> None:
        if deck:
            text = "Deck status: selected"
        else:
            text = "Deck status: not selected"
        self._deck_status_label.set_text(text)


def missing_required_fields(mapping: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for key in ("word", "translation", "example_en", "definitions_en", "image"):
        value = mapping.get(key, "")
        if not value:
            missing.append(key)
    return missing


def _model_exists_error(message: str) -> bool:
    return "already exists" in message.casefold()
