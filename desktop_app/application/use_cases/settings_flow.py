from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future

from desktop_app.application.anki_status import AnkiActionResult, AnkiStatus
from desktop_app.application.dispatch import Dispatch, call_inline
from desktop_app.application.use_cases.anki_flow import AnkiFlow
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig
from desktop_app.infrastructure.anki import AnkiCreateModelResult, AnkiListResult
from desktop_app.infrastructure.anki.templates import (
    DEFAULT_BACK_TEMPLATE,
    DEFAULT_FRONT_TEMPLATE,
    DEFAULT_MODEL_CSS,
    DEFAULT_MODEL_FIELDS,
    DEFAULT_MODEL_NAME,
)
from desktop_app.infrastructure.notifications import messages as notify_messages
from desktop_app.infrastructure.services.runtime import AsyncRuntime

_DEFAULT_FIELD_MAP = AnkiFieldMap(
    word="word",
    translation="translation",
    example_en="example_en",
    definitions_en="definitions_en",
    image="image",
)
_EMPTY_FIELD_MAP = AnkiFieldMap(
    word="",
    translation="",
    example_en="",
    definitions_en="",
    image="",
)


class SettingsFlow:
    """UI-agnostic settings/Anki model orchestration.

    Completion callbacks from the async runtime are marshalled through
    ``dispatch`` so subclasses can pin them to their own main loop.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        runtime: AsyncRuntime,
        anki_flow: AnkiFlow,
        on_save: Callable[[AppConfig], None],
        dispatch: Dispatch = call_inline,
        on_reachability: Callable[[bool], None] | None = None,
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._anki_flow = anki_flow
        self._on_save = on_save
        self._dispatch = dispatch
        self._on_reachability = on_reachability
        self._pending_anki: AnkiConfig | None = config.anki
        self._model_ready = False
        self._model_names_future: Future[AnkiListResult] | None = None
        self._create_model_future: Future[AnkiCreateModelResult] | None = None
        self._deck_names_future: Future[AnkiListResult] | None = None
        self._model_fields_future: Future[AnkiListResult] | None = None
        self._status_waiters: list[Callable[[AnkiStatus], None]] = []
        self._refresh_model_status()

    @property
    def config(self) -> AppConfig:
        return self._config

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
        if self._model_ready:
            reply(
                self._action_result(
                    notify_messages.anki_model_exists(DEFAULT_MODEL_NAME).message
                )
            )
            return
        deck = self._current_deck()
        self._start_create_model(deck, reply)

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
            lambda done: self._dispatch(lambda: self._on_deck_names_ready(done, reply))
        )

    def list_model_fields(self, reply: Callable[[AnkiListResult], None]) -> None:
        """The field names Anki really has, so a typo is visible where it is made.

        Deliberately not folded into saving: Anki is another program and may
        simply be closed, and settings must stay savable when it is. The caller
        gets the names or the reason there are none, and decides what to show.
        """
        model = self._current_model()
        if not model:
            reply(AnkiListResult(items=[], error="No note type is configured."))
            return
        if not self._runtime_ready():
            reply(AnkiListResult(items=[], error="Anki runtime is not ready."))
            return
        if (
            self._model_fields_future is not None
            and not self._model_fields_future.done()
        ):
            reply(AnkiListResult(items=[], error="Field list is already in progress."))
            return
        try:
            self._model_fields_future = self._anki_flow.model_fields(model)
        except Exception:
            reply(AnkiListResult(items=[], error="Failed to load Anki field names."))
            return
        self._model_fields_future.add_done_callback(
            lambda done: self._dispatch(
                lambda: self._on_model_fields_ready(done, reply)
            )
        )

    def _on_model_fields_ready(
        self,
        future: Future[AnkiListResult],
        reply: Callable[[AnkiListResult], None],
    ) -> None:
        if future.cancelled():
            reply(AnkiListResult(items=[], error="Field list was cancelled."))
            return
        try:
            result = future.result()
        except Exception:
            self._report_reachability(False)
            reply(AnkiListResult(items=[], error="Failed to load Anki field names."))
            return
        self._report_reachability(result.error is None)
        reply(result)

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
            lambda done: self._dispatch(
                lambda: self._on_select_deck_done(done, deck, reply)
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

    def save_config(
        self, config: AppConfig, reply: Callable[[AnkiActionResult], None]
    ) -> None:
        self._config = config
        self._pending_anki = config.anki
        self._on_save(config)
        self._refresh_model_status()
        reply(self._action_result(notify_messages.settings_saved().message))

    def current_status(self) -> AnkiStatus:
        return self._current_status()

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
            lambda done: self._dispatch(lambda: self._on_model_status_ready(done))
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
    ) -> None:
        if future.cancelled():
            reply(AnkiListResult(items=[], error="Deck list was cancelled."))
            return
        try:
            result = future.result()
        except Exception:
            self._report_reachability(False)
            reply(AnkiListResult(items=[], error="Failed to load Anki decks."))
            return
        self._report_reachability(result.error is None)
        reply(result)

    def _on_select_deck_done(
        self,
        future: Future[AnkiListResult],
        deck: str,
        reply: Callable[[AnkiActionResult], None],
    ) -> None:
        if future.cancelled():
            reply(self._action_result("Deck list was cancelled."))
            return
        try:
            result = future.result()
        except Exception:
            reply(
                self._action_result(
                    notify_messages.settings_error("Failed to load Anki decks.").message
                )
            )
            return
        if result.error is not None:
            reply(
                self._action_result(
                    notify_messages.settings_error(result.error).message
                )
            )
            return
        if deck not in result.items:
            reply(self._action_result(notify_messages.anki_deck_missing().message))
            return
        if self._model_ready:
            fields = _DEFAULT_FIELD_MAP
            model = DEFAULT_MODEL_NAME
        else:
            fields = _EMPTY_FIELD_MAP
            model = ""
        self._pending_anki = AnkiConfig(
            deck=deck,
            model=model,
            fields=fields,
        )
        self._persist_anki(self._pending_anki)
        reply(self._action_result(notify_messages.anki_deck_selected(deck).message))

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
            lambda done: self._dispatch(
                lambda: self._on_create_model_done(done, deck, reply)
            )
        )

    def _on_create_model_done(
        self,
        future: Future[AnkiCreateModelResult],
        deck: str,
        reply: Callable[[AnkiActionResult], None],
    ) -> None:
        if future.cancelled():
            reply(self._action_result("Model creation was cancelled."))
            return
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
            return
        if result.error is not None:
            reply(
                self._action_result(
                    notify_messages.settings_error(result.error).message
                )
            )
            return
        self._apply_created_model(deck)
        reply(
            self._action_result(
                notify_messages.model_created(DEFAULT_MODEL_NAME).message
            )
        )

    def _on_model_status_ready(self, future: Future[AnkiListResult]) -> None:
        if future.cancelled():
            self._model_ready = False
            self._flush_status_waiters()
            return
        try:
            result = future.result()
        except Exception:
            self._model_ready = False
            self._report_reachability(False)
            self._flush_status_waiters()
            return
        self._report_reachability(result.error is None)
        if result.error is not None:
            self._model_ready = False
            self._flush_status_waiters()
            return
        default_key = DEFAULT_MODEL_NAME.casefold()
        has_default = any(item.casefold() == default_key for item in result.items)
        has_legacy = any(
            item.casefold().startswith(f"{default_key} ") for item in result.items
        )
        self._model_ready = has_default and not has_legacy
        if self._model_ready and self._config.anki.model != DEFAULT_MODEL_NAME:
            self._apply_created_model(self._current_deck())
        self._flush_status_waiters()

    def _apply_created_model(self, deck: str) -> None:
        self._model_ready = True
        target_deck = deck or self._current_deck()
        self._pending_anki = AnkiConfig(
            deck=target_deck,
            model=DEFAULT_MODEL_NAME,
            fields=_DEFAULT_FIELD_MAP,
        )
        self._persist_anki(self._pending_anki)

    def _current_model(self) -> str:
        pending = self._pending_anki
        return pending.model if pending is not None else self._config.anki.model

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
            lambda done: self._dispatch(lambda: self._on_model_status_ready(done))
        )

    def _action_result(self, message: str) -> AnkiActionResult:
        return AnkiActionResult(message=message, status=self._current_status())

    def _report_reachability(self, reachable: bool) -> None:
        if self._on_reachability is not None:
            self._on_reachability(reachable)

    def _runtime_ready(self) -> bool:
        try:
            _ = self._runtime.loop
        except RuntimeError:
            return False
        return True
