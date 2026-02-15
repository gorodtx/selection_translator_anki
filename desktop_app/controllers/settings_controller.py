from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
import importlib

from desktop_app.anki import AnkiCreateModelResult, AnkiListResult
from desktop_app.anki.templates import (
    DEFAULT_BACK_TEMPLATE,
    DEFAULT_FRONT_TEMPLATE,
    DEFAULT_MODEL_CSS,
    DEFAULT_MODEL_FIELDS,
    DEFAULT_MODEL_NAME,
)
from desktop_app.application.anki_flow import AnkiFlow
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig
from desktop_app.notifications import messages as notify_messages
from desktop_app.services.runtime import AsyncRuntime

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("GLib", "2.0")
GLib = importlib.import_module("gi.repository.GLib")


@dataclass(frozen=True, slots=True)
class AnkiStatus:
    model_status: str
    deck_status: str
    deck_name: str


@dataclass(frozen=True, slots=True)
class AnkiActionResult:
    message: str
    status: AnkiStatus


class SettingsController:
    def __init__(
        self,
        *,
        config: AppConfig,
        runtime: AsyncRuntime,
        anki_flow: AnkiFlow,
        on_save: Callable[[AppConfig], None],
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._anki_flow = anki_flow
        self._on_save = on_save
        self._pending_anki: AnkiConfig | None = config.anki
        self._model_ready = False
        self._model_names_future: Future[AnkiListResult] | None = None
        self._create_model_future: Future[AnkiCreateModelResult] | None = None
        self._deck_names_future: Future[AnkiListResult] | None = None
        self._status_waiters: list[Callable[[AnkiStatus], None]] = []
        self._refresh_model_status()

    def update_config(self, config: AppConfig) -> None:
        self._config = config
        self._pending_anki = config.anki
        self._refresh_model_status()

    def get_anki_status(self, reply: Callable[[AnkiStatus], None]) -> None:
        self._status_waiters.append(reply)
        if not self._ensure_model_status_refresh():
            self._flush_status_waiters()

    def create_model(self, reply: Callable[[AnkiActionResult], None]) -> None:
        if not self._runtime_ready():
            reply(self._action_result("Anki runtime is not ready."))
            return
        if (
            self._create_model_future is not None
            and not self._create_model_future.done()
        ):
            reply(self._action_result("Model creation is already in progress."))
            return
        if self._model_names_future is not None and not self._model_names_future.done():
            reply(self._action_result("Model check is already in progress."))
            return
        if self._model_ready:
            reply(
                self._action_result(
                    notify_messages.anki_model_exists(DEFAULT_MODEL_NAME).message
                )
            )
            return
        try:
            self._model_names_future = self._anki_flow.model_names()
        except Exception:
            reply(
                self._action_result(
                    notify_messages.settings_error(
                        "Failed to check Anki models."
                    ).message
                )
            )
            return
        self._model_names_future.add_done_callback(
            lambda done: GLib.idle_add(self._on_model_names_ready, done, reply)
        )

    def list_decks(self, reply: Callable[[AnkiListResult], None]) -> None:
        if not self._runtime_ready():
            reply(AnkiListResult(items=[], error="Anki runtime is not ready."))
            return
        if self._deck_names_future is not None and not self._deck_names_future.done():
            reply(AnkiListResult(items=[], error="Deck list is already in progress."))
            return
        try:
            self._deck_names_future = self._anki_flow.refresh_decks()
        except Exception:
            reply(AnkiListResult(items=[], error="Failed to load Anki decks."))
            return
        self._deck_names_future.add_done_callback(
            lambda done: GLib.idle_add(self._on_deck_names_ready, done, reply)
        )

    def select_deck(
        self,
        deck: str,
        reply: Callable[[AnkiActionResult], None],
    ) -> None:
        if not self._runtime_ready():
            reply(self._action_result("Anki runtime is not ready."))
            return
        if not deck:
            reply(self._action_result("Deck name is empty."))
            return
        if self._deck_names_future is not None and not self._deck_names_future.done():
            reply(self._action_result("Deck list is already in progress."))
            return
        try:
            self._deck_names_future = self._anki_flow.refresh_decks()
        except Exception:
            reply(
                self._action_result(
                    notify_messages.settings_error("Failed to load Anki decks.").message
                )
            )
            return
        self._deck_names_future.add_done_callback(
            lambda done: GLib.idle_add(
                self._on_select_deck_done,
                done,
                deck,
                reply,
            )
        )

    def save_settings(self, reply: Callable[[AnkiActionResult], None]) -> None:
        anki_config = self._pending_anki or self._config.anki
        new_config = AppConfig(
            languages=self._config.languages,
            anki=anki_config,
        )
        self._on_save(new_config)
        reply(self._action_result(notify_messages.settings_saved().message))

    def _ensure_model_status_refresh(self) -> bool:
        if self._model_names_future is not None and not self._model_names_future.done():
            return True
        if not self._runtime_ready():
            self._model_ready = False
            return False
        try:
            self._model_names_future = self._anki_flow.model_names()
        except Exception:
            self._model_ready = False
            return False
        self._model_names_future.add_done_callback(
            lambda done: GLib.idle_add(self._on_model_status_ready, done)
        )
        return True

    def _flush_status_waiters(self) -> None:
        if not self._status_waiters:
            return
        status = self._current_status()
        for waiter in self._status_waiters:
            try:
                waiter(status)
            except Exception:
                continue
        self._status_waiters.clear()

    def _current_status(self) -> AnkiStatus:
        anki = self._pending_anki or self._config.anki
        model_status = "Model ready" if self._model_ready else "Model not found"
        deck_status = "Selected" if anki.deck else "Not selected"
        return AnkiStatus(
            model_status=model_status,
            deck_status=deck_status,
            deck_name=anki.deck,
        )

    def _on_deck_names_ready(
        self,
        future: Future[AnkiListResult],
        reply: Callable[[AnkiListResult], None],
    ) -> bool:
        if future.cancelled():
            reply(AnkiListResult(items=[], error="Deck list was cancelled."))
            return False
        try:
            result = future.result()
        except Exception:
            reply(AnkiListResult(items=[], error="Failed to load Anki decks."))
            return False
        reply(result)
        return False

    def _on_select_deck_done(
        self,
        future: Future[AnkiListResult],
        deck: str,
        reply: Callable[[AnkiActionResult], None],
    ) -> bool:
        if future.cancelled():
            reply(self._action_result("Deck list was cancelled."))
            return False
        try:
            result = future.result()
        except Exception:
            reply(
                self._action_result(
                    notify_messages.settings_error("Failed to load Anki decks.").message
                )
            )
            return False
        if result.error is not None:
            reply(
                self._action_result(
                    notify_messages.settings_error(result.error).message
                )
            )
            return False
        if deck not in result.items:
            reply(self._action_result(notify_messages.anki_deck_missing().message))
            return False
        if self._model_ready:
            fields = AnkiFieldMap(
                word="word",
                translation="translation",
                example_en="example_en",
                definitions_en="definitions_en",
            )
            model = DEFAULT_MODEL_NAME
        else:
            fields = AnkiFieldMap(
                word="",
                translation="",
                example_en="",
                definitions_en="",
            )
            model = ""
        self._pending_anki = AnkiConfig(
            deck=deck,
            model=model,
            fields=fields,
        )
        self._persist_anki(self._pending_anki)
        reply(self._action_result(notify_messages.anki_deck_selected(deck).message))
        return False

    def _on_model_names_ready(
        self,
        future: Future[AnkiListResult],
        reply: Callable[[AnkiActionResult], None],
    ) -> bool:
        if future.cancelled():
            reply(self._action_result("Model check was cancelled."))
            return False
        try:
            result = future.result()
        except Exception:
            reply(
                self._action_result(
                    notify_messages.settings_error(
                        "Failed to check Anki models."
                    ).message
                )
            )
            return False
        if result.error is not None:
            reply(
                self._action_result(
                    notify_messages.settings_error(result.error).message
                )
            )
            return False
        deck = self._current_deck()
        if DEFAULT_MODEL_NAME in result.items:
            self._apply_created_model(deck)
            reply(
                self._action_result(
                    notify_messages.anki_model_exists(DEFAULT_MODEL_NAME).message
                )
            )
            return False
        self._start_create_model(deck, reply)
        return False

    def _start_create_model(
        self,
        deck: str,
        reply: Callable[[AnkiActionResult], None],
    ) -> None:
        if (
            self._create_model_future is not None
            and not self._create_model_future.done()
        ):
            reply(self._action_result("Model creation is already in progress."))
            return
        self._create_model_future = self._anki_flow.create_model(
            DEFAULT_MODEL_NAME,
            DEFAULT_MODEL_FIELDS,
            DEFAULT_FRONT_TEMPLATE,
            DEFAULT_BACK_TEMPLATE,
            DEFAULT_MODEL_CSS,
        )
        self._create_model_future.add_done_callback(
            lambda done: GLib.idle_add(self._on_create_model_done, done, deck, reply)
        )

    def _on_create_model_done(
        self,
        future: Future[AnkiCreateModelResult],
        deck: str,
        reply: Callable[[AnkiActionResult], None],
    ) -> bool:
        if future.cancelled():
            reply(self._action_result("Model creation was cancelled."))
            return False
        try:
            result = future.result()
        except Exception:
            reply(
                self._action_result(
                    notify_messages.settings_error(
                        "Failed to create Anki model."
                    ).message
                )
            )
            return False
        if result.error is not None:
            if _model_exists_error(result.error):
                self._apply_created_model(deck)
                reply(
                    self._action_result(
                        notify_messages.anki_model_exists(DEFAULT_MODEL_NAME).message
                    )
                )
                return False
            reply(
                self._action_result(
                    notify_messages.settings_error(result.error).message
                )
            )
            return False
        self._apply_created_model(deck)
        reply(
            self._action_result(
                notify_messages.model_created(DEFAULT_MODEL_NAME).message
            )
        )
        return False

    def _on_model_status_ready(self, future: Future[AnkiListResult]) -> bool:
        if future.cancelled():
            self._model_ready = False
            self._flush_status_waiters()
            return False
        try:
            result = future.result()
        except Exception:
            self._model_ready = False
            self._flush_status_waiters()
            return False
        if result.error is not None:
            self._model_ready = False
            self._flush_status_waiters()
            return False
        self._model_ready = DEFAULT_MODEL_NAME in result.items
        if self._model_ready and self._config.anki.model != DEFAULT_MODEL_NAME:
            self._apply_created_model(self._current_deck())
        self._flush_status_waiters()
        return False

    def _apply_created_model(self, deck: str) -> None:
        self._model_ready = True
        target_deck = deck or self._current_deck()
        fields = AnkiFieldMap(
            word="word",
            translation="translation",
            example_en="example_en",
            definitions_en="definitions_en",
        )
        self._pending_anki = AnkiConfig(
            deck=target_deck,
            model=DEFAULT_MODEL_NAME,
            fields=fields,
        )
        self._persist_anki(self._pending_anki)

    def _current_deck(self) -> str:
        if self._pending_anki is not None and self._pending_anki.deck:
            return self._pending_anki.deck
        return self._config.anki.deck

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
        if not self._runtime_ready():
            self._model_ready = False
            return
        try:
            self._model_names_future = self._anki_flow.model_names()
        except Exception:
            self._model_ready = False
            return
        self._model_names_future.add_done_callback(
            lambda done: GLib.idle_add(self._on_model_status_ready, done)
        )

    def _action_result(self, message: str) -> AnkiActionResult:
        return AnkiActionResult(message=message, status=self._current_status())

    def _runtime_ready(self) -> bool:
        try:
            _ = self._runtime.loop
        except RuntimeError:
            return False
        return True


def _model_exists_error(message: str) -> bool:
    return "already exists" in message.casefold()
