"""Headless translation session driving the shared application layer.

Mirrors the GNOME ``TranslationController`` state machine but emits protocol
events instead of touching widgets. Every public method must be called on the
daemon main loop; completion callbacks from the async runtime are marshalled
back through ``dispatch``.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.application.anki_status import AnkiActionResult, AnkiStatus
from desktop_app.application.dispatch import Dispatch
from desktop_app.application.history import HistoryItem
from desktop_app.application.use_cases.anki_upsert import (
    AnkiUpsertDecision,
    AnkiUpsertPreview,
)
from desktop_app.application.use_cases.anki_upsert_flow import AnkiUpsertCoordinator
from desktop_app.application.use_cases.example_refresh import (
    ExampleRefreshResult,
    ExampleRefreshUseCase,
)
from desktop_app.application.use_cases.settings_flow import SettingsFlow
from desktop_app.application.use_cases.translation_executor import TranslationExecutor
from desktop_app.application.view_state import (
    TranslationPresenter,
    TranslationViewState,
)
from desktop_app.config import AppConfig
from desktop_app.infrastructure.anki import AnkiListResult
from desktop_app.infrastructure.anki.templates import DEFAULT_MODEL_NAME
from desktop_app.infrastructure.notifications import messages as notify_messages
from desktop_app.infrastructure.notifications.models import Notification
from desktop_app.infrastructure.services.container import AppServices
from desktop_app.platform.macos.ipc.protocol import (
    ErrorCode,
    Event,
    JsonObject,
    Phase,
    notification_to_json,
    translation_state_event,
)
from desktop_app.application.translation_state import TranslationState
from translate_logic.models import (
    Example,
    LexicalInfo,
    TranslationResult,
    TranslationStatus,
)
from translate_logic.shared.highlight import build_highlight_spec, highlight_to_markdown

type Emit = Callable[[Event, JsonObject], None]


class SessionError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    request_id: int
    state: TranslationViewState
    entry_id: int | None
    lexical: LexicalInfo | None = None
    translation_raw: str | None = None


@dataclass(frozen=True, slots=True)
class UpsertOutcome:
    outcome: str
    message: str


class BackendSession:
    def __init__(
        self,
        *,
        services: AppServices,
        config: AppConfig,
        dispatch: Dispatch,
        emit: Emit,
        save_config: Callable[[AppConfig], None],
    ) -> None:
        self._services = services
        self._config = config
        self._dispatch = dispatch
        self._emit = emit
        self._save_config = save_config
        self._executor = TranslationExecutor(
            flow=services.translation_flow, config=config
        )
        self._examples_refresh = ExampleRefreshUseCase(
            translation_executor=self._executor
        )
        self._anki = AnkiUpsertCoordinator(
            anki_flow=services.anki_flow, dispatch=dispatch
        )
        self._settings = SettingsFlow(
            config=config,
            runtime=services.runtime,
            anki_flow=services.anki_flow,
            on_save=self._on_settings_saved,
            dispatch=dispatch,
            on_reachability=self._set_anki_available_flag,
        )
        self._state = TranslationState()
        self._presenter = TranslationPresenter()
        self._translation_future: Future[TranslationResult] | None = None
        self._examples_future: Future[ExampleRefreshResult] | None = None
        self._pending_preview: AnkiUpsertPreview | None = None
        self._anki_available = True

    # --- snapshot ------------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        return self._config

    def snapshot(self) -> StateSnapshot:
        return StateSnapshot(
            request_id=self._state.request.current_id,
            state=self._presenter.state,
            entry_id=self._state.memory.entry_id,
            lexical=self._current_lexical(),
            translation_raw=self._current_translation_raw(),
        )

    # --- translation ----------------------------------------------------------

    def translate(self, text: str) -> StateSnapshot:
        self._set_anki_available(True, announce=False)
        raw_text = text.strip() if text else ""
        if not raw_text:
            raise SessionError(ErrorCode.INVALID_PARAMS, "Text is empty.")
        prepared = self._executor.prepare(raw_text)
        if prepared is None:
            raise SessionError(
                ErrorCode.INVALID_PARAMS, "Text has no translatable English content."
            )
        if self._state.memory.can_reuse(
            prepared.display_text, loading=self._presenter.state.loading
        ):
            self._presenter.reset_original(prepared.display_text)
            if self._state.memory.result is not None:
                self._apply_current_result()
            self._emit_state(Phase.FINAL)
            return self.snapshot()
        self.cancel()
        request_id = self._state.request.next_id()
        if prepared.cached is not None:
            self._remember_success_result(
                display_text=prepared.display_text,
                lookup_text=prepared.lookup_text,
                result=prepared.cached,
            )
            self._presenter.begin(prepared.display_text)
            self._apply_current_result()
            self._emit_state(Phase.FINAL)
            return self.snapshot()
        self._state.memory.update(
            prepared.display_text, None, lookup_text=prepared.lookup_text
        )
        self._presenter.begin(prepared.display_text)
        self._emit_state(Phase.BEGIN)
        self._start_translation(
            request_id,
            prepared.display_text,
            prepared.network_text,
            prepared.lookup_text,
        )
        return self.snapshot()

    def cancel(self) -> None:
        self._state.request.invalidate()
        if self._translation_future is not None:
            self._translation_future.cancel()
            self._translation_future = None
        if self._examples_future is not None:
            self._examples_future.cancel()
            self._examples_future = None
        self._pending_preview = None
        self._anki.cancel_pending()
        self._services.cancel_active()

    def _start_translation(
        self,
        request_id: int,
        display_text: str,
        network_text: str,
        lookup_text: str,
    ) -> None:
        if not self._state.request.is_active(request_id):
            return

        def on_start(text: str) -> None:
            del text

        def on_partial(result: TranslationResult) -> None:
            self._dispatch(lambda: self._apply_partial(request_id, result))

        def on_complete(result: TranslationResult) -> None:
            self._dispatch(lambda: self._apply_final(request_id, result))

        def on_error() -> None:
            self._dispatch(lambda: self._apply_error(request_id))

        self._translation_future = self._executor.run(
            display_text,
            network_text,
            lookup_text,
            on_start=on_start,
            on_partial=on_partial,
            on_complete=on_complete,
            on_error=on_error,
        )

    def _apply_partial(self, request_id: int, result: TranslationResult) -> None:
        if not self._state.request.is_active(request_id):
            return
        if result.status is not TranslationStatus.SUCCESS:
            return
        self._state.memory.update(
            self._state.memory.text,
            result,
            lookup_text=self._state.memory.lookup_text,
        )
        self._presenter.apply_partial(result)
        self._emit_state(Phase.PARTIAL)

    def _apply_final(self, request_id: int, result: TranslationResult) -> None:
        if not self._state.request.is_active(request_id):
            return
        self._translation_future = None
        self._remember_success_result(
            display_text=self._state.memory.text,
            lookup_text=self._state.memory.lookup_text,
            result=result,
        )
        self._apply_current_result()
        self._emit_state(Phase.FINAL)

    def _apply_error(self, request_id: int) -> None:
        if not self._state.request.is_active(request_id):
            return
        self._translation_future = None
        self._presenter.mark_error()
        self._notify(notify_messages.translation_error())
        self._emit_state(Phase.ERROR)

    # --- history ---------------------------------------------------------------

    def history(self) -> list[HistoryItem]:
        return self._executor.history_snapshot()

    def select_history(self, entry_id: int) -> StateSnapshot:
        item = next(
            (entry for entry in self.history() if entry.entry_id == entry_id), None
        )
        if item is None:
            raise SessionError(
                ErrorCode.NO_ACTIVE_ENTRY, f"No history entry {entry_id}."
            )
        if item.result.status is not TranslationStatus.SUCCESS:
            raise SessionError(ErrorCode.NO_ACTIVE_ENTRY, "Entry has no translation.")
        self.cancel()
        self._state.request.next_id()
        self._state.memory.set_entry(item)
        self._presenter.begin(item.text)
        self._apply_current_result()
        self._emit_state(Phase.FINAL)
        return self.snapshot()

    # --- examples --------------------------------------------------------------

    def refresh_examples(self, reply: Callable[[StateSnapshot, bool], None]) -> None:
        entry = self._current_history_item()
        if entry is None:
            raise SessionError(ErrorCode.NO_ACTIVE_ENTRY, "No active translation.")
        if entry.examples_state.exhausted:
            self._notify(notify_messages.no_more_examples())
            reply(self.snapshot(), False)
            return
        request_id = self._state.request.current_id
        self._presenter.set_examples_refreshing(
            refreshing_examples=True,
            can_refresh_examples=self._can_refresh_examples(),
        )
        self._emit_state(Phase.EXAMPLES)
        future = self._examples_refresh.refresh_entry(entry)
        future.add_done_callback(
            lambda done: self._dispatch(
                lambda: self._apply_examples_refresh(
                    request_id, entry.entry_id, done, reply
                )
            )
        )
        self._examples_future = future

    def _apply_examples_refresh(
        self,
        request_id: int,
        entry_id: int,
        future: Future[ExampleRefreshResult],
        reply: Callable[[StateSnapshot, bool], None],
    ) -> None:
        if not self._state.request.is_active(request_id):
            reply(self.snapshot(), False)
            return
        if self._state.memory.entry_id != entry_id:
            reply(self.snapshot(), False)
            return
        self._examples_future = None
        if future.cancelled():
            self._presenter.set_examples_refreshing(
                refreshing_examples=False,
                can_refresh_examples=self._can_refresh_examples(),
            )
            self._emit_state(Phase.EXAMPLES)
            reply(self.snapshot(), False)
            return
        try:
            refresh_result = future.result()
        except Exception as exc:
            self._presenter.set_examples_refreshing(
                refreshing_examples=False,
                can_refresh_examples=self._can_refresh_examples(),
            )
            self._notify(
                notify_messages.examples_refresh_error(
                    str(exc) or "Failed to refresh examples."
                )
            )
            self._emit_state(Phase.EXAMPLES)
            reply(self.snapshot(), False)
            return
        self._state.memory.set_entry(refresh_result.item)
        self._presenter.update_examples(
            examples=refresh_result.item.examples_state.visible_examples,
            can_refresh_examples=self._can_refresh_examples(),
            refreshing_examples=False,
        )
        if not refresh_result.changed:
            self._notify(notify_messages.no_more_examples())
        self._emit_state(Phase.EXAMPLES)
        reply(self.snapshot(), refresh_result.changed)

    # --- clipboard -------------------------------------------------------------

    def copy_all_text(self) -> str:
        result = self._state.memory.result
        if result is None:
            raise SessionError(ErrorCode.NO_ACTIVE_ENTRY, "No active translation.")
        lines: list[str] = []
        original = self._state.memory.text.strip()
        highlight_spec = build_highlight_spec(original)
        if original:
            lines.append(f"Original: {original}")
        if result.translation_ru.is_present:
            lines.append(f"Translation: {result.translation_ru.text}")
        if result.definitions_en:
            lines.append("Definitions EN:")
            for index, definition in enumerate(result.definitions_en, start=1):
                highlighted = highlight_to_markdown(definition, highlight_spec)
                lines.append(f"{index}. {highlighted}")
        visible_examples = self._current_visible_examples()
        if visible_examples:
            lines.append("Examples:")
            for index, example in enumerate(visible_examples, start=1):
                highlighted = highlight_to_markdown(example.en, highlight_spec)
                lines.append(f"{index}. EN: {highlighted}")
        text = "\n".join(lines)
        if text:
            self._notify(notify_messages.copy_success())
        return text

    # --- anki ------------------------------------------------------------------

    def anki_status(self, reply: Callable[[AnkiStatus], None]) -> None:
        self._settings.get_anki_status(reply)

    @property
    def anki_available(self) -> bool:
        return self._anki_available

    def anki_decks(self, reply: Callable[[AnkiListResult], None]) -> None:
        self._settings.list_decks(reply)

    def anki_select_deck(
        self, deck: str, reply: Callable[[AnkiActionResult], None]
    ) -> None:
        self._settings.select_deck(deck, reply)

    def anki_create_model(self, reply: Callable[[AnkiActionResult], None]) -> None:
        self._settings.create_model(reply)

    def anki_prepare_upsert(
        self,
        reply: Callable[[AnkiUpsertPreview | None, str | None], None],
    ) -> None:
        result = self._state.memory.result
        if result is None or result.status is not TranslationStatus.SUCCESS:
            raise SessionError(ErrorCode.NO_ACTIVE_ENTRY, "No successful translation.")
        if not self._anki.is_config_ready(self._config.anki):
            if not self._config.anki.deck:
                self._notify(notify_messages.anki_deck_missing())
            if not self._config.anki.model:
                self._notify(notify_messages.anki_model_required(DEFAULT_MODEL_NAME))
            raise SessionError(
                ErrorCode.NOT_READY, "Anki deck or model is not configured."
            )
        request_id = self._state.request.current_id
        replied = False

        def _reply_once(preview: AnkiUpsertPreview | None, error: str | None) -> None:
            nonlocal replied
            if replied:
                return
            replied = True
            reply(preview, error)

        def _on_ready(preview: AnkiUpsertPreview) -> None:
            self._pending_preview = preview
            _reply_once(preview, None)

        def _notify(notification: Notification) -> None:
            self._notify(notification)
            _reply_once(None, notification.message)

        self._anki.prepare_upsert(
            request_id=request_id,
            config=self._config.anki,
            original_text=self._state.memory.text,
            result=result,
            examples_override=self._current_collected_example_texts(),
            is_request_active=self._state.request.is_active,
            on_ready=_on_ready,
            set_anki_available=self._set_anki_available_flag,
            notify=_notify,
        )

    def anki_apply_upsert(
        self,
        decision: AnkiUpsertDecision,
        reply: Callable[[UpsertOutcome], None],
    ) -> None:
        preview = self._pending_preview
        if preview is None:
            raise SessionError(ErrorCode.NO_ACTIVE_ENTRY, "Prepare an upsert first.")
        request_id = self._state.request.current_id
        replied = False

        def _reply_once(outcome: str, message: str) -> None:
            nonlocal replied
            if replied:
                return
            replied = True
            reply(UpsertOutcome(outcome=outcome, message=message))

        def _on_success() -> None:
            self._notify(notify_messages.anki_success())
            _reply_once("success", notify_messages.anki_success().message)

        def _on_updated() -> None:
            self._notify(notify_messages.anki_updated())
            _reply_once("updated", notify_messages.anki_updated().message)

        def _on_unchanged() -> None:
            self._notify(notify_messages.anki_unchanged())
            _reply_once("unchanged", notify_messages.anki_unchanged().message)

        def _notify(notification: Notification) -> None:
            self._notify(notification)
            _reply_once(_outcome_for_notification(notification), notification.message)

        self._anki.apply_upsert(
            request_id=request_id,
            config=self._config.anki,
            original_text=self._state.memory.text,
            preview=preview,
            decision=decision,
            is_request_active=self._state.request.is_active,
            on_success=_on_success,
            on_updated=_on_updated,
            on_unchanged=_on_unchanged,
            set_anki_available=self._set_anki_available_flag,
            notify=_notify,
        )

    # --- settings --------------------------------------------------------------

    def save_settings(
        self, config: AppConfig, reply: Callable[[AnkiActionResult], None]
    ) -> None:
        self._settings.save_config(config, reply)

    def _on_settings_saved(self, config: AppConfig) -> None:
        self._config = config
        self._executor.update_config(config)
        # A source the user just switched off must stop being consulted, and
        # results produced while it was on must not be served from the cache.
        self._services.translator.update_sources(config.sources)
        self._save_config(config)

    # --- internals -------------------------------------------------------------

    def _emit_state(self, phase: Phase) -> None:
        self._emit(
            Event.TRANSLATION_STATE,
            translation_state_event(
                request_id=self._state.request.current_id,
                phase=phase,
                state=self._presenter.state,
                entry_id=self._state.memory.entry_id,
                lexical=self._current_lexical(),
                translation_raw=self._current_translation_raw(),
            ),
        )

    def _current_translation_raw(self) -> str | None:
        result = self._state.memory.result
        if result is None or not result.translation_ru.is_present:
            return None
        if not self._presenter.state.translation.strip():
            return None
        return result.translation_ru.text

    def _current_lexical(self) -> LexicalInfo | None:
        result = self._state.memory.result
        if result is None or self._presenter.state.loading:
            return None
        return result.lexical

    def _notify(self, notification: Notification) -> None:
        self._emit(Event.NOTIFICATION, notification_to_json(notification))

    def _set_anki_available_flag(self, available: bool) -> None:
        self._set_anki_available(available, announce=True)

    def _set_anki_available(self, available: bool, *, announce: bool) -> None:
        changed = available != self._anki_available
        self._anki_available = available
        self._presenter.set_anki_available(available)
        if announce and changed:
            self._emit(Event.ANKI_AVAILABILITY, {"available": available})

    def _remember_success_result(
        self,
        *,
        display_text: str,
        lookup_text: str,
        result: TranslationResult,
    ) -> None:
        history_item = self._executor.register_result(display_text, lookup_text, result)
        if history_item is not None:
            self._state.memory.set_entry(history_item)
            return
        self._state.memory.update(display_text, result, lookup_text=lookup_text)

    def _apply_current_result(self) -> None:
        result = self._state.memory.result
        if result is None:
            return
        self._presenter.apply_final(
            result,
            visible_examples=self._current_visible_examples(),
            can_refresh_examples=self._can_refresh_examples(),
            refreshing_examples=False,
        )

    def _can_refresh_examples(self) -> bool:
        result = self._state.memory.result
        if result is None or result.status is not TranslationStatus.SUCCESS:
            return False
        return bool(self._state.memory.lookup_text.strip())

    def _current_visible_examples(self) -> tuple[Example, ...]:
        if self._state.memory.examples_state is not None:
            return self._state.memory.examples_state.visible_examples
        result = self._state.memory.result
        if result is None:
            return ()
        return tuple(result.examples[:3])

    def _current_collected_example_texts(self) -> tuple[str, ...]:
        if self._state.memory.examples_state is None:
            result = self._state.memory.result
            if result is None:
                return ()
            return tuple(
                example.en for example in result.examples if example.en.strip()
            )
        return tuple(
            example.en
            for example in self._state.memory.examples_state.collected_examples
            if example.en.strip()
        )

    def _current_history_item(self) -> HistoryItem | None:
        if (
            self._state.memory.entry_id is None
            or self._state.memory.result is None
            or self._state.memory.examples_state is None
        ):
            return None
        return HistoryItem(
            entry_id=self._state.memory.entry_id,
            text=self._state.memory.text,
            lookup_text=self._state.memory.lookup_text,
            result=self._state.memory.result,
            examples_state=self._state.memory.examples_state,
        )


def _outcome_for_notification(notification: Notification) -> str:
    message = notification.message
    if message == notify_messages.anki_duplicate().message:
        return "duplicate"
    if message == notify_messages.anki_unavailable().message:
        return "unavailable"
    return "error"
