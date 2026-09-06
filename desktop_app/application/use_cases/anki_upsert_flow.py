from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future

from desktop_app.application.dispatch import Dispatch, call_inline
from desktop_app.application.use_cases.anki_flow import (
    AnkiFlow,
    AnkiOutcome,
    AnkiResult,
    AnkiUpsertPreviewResult,
)
from desktop_app.application.use_cases.anki_upsert import (
    AnkiUpsertDecision,
    AnkiUpsertPreview,
)
from desktop_app.config import AnkiConfig
from desktop_app.infrastructure.anki import AnkiListResult
from desktop_app.infrastructure.notifications import messages as notify_messages
from desktop_app.infrastructure.notifications.models import Notification
from translate_logic.models import TranslationResult


class AnkiUpsertCoordinator:
    """UI-agnostic prepare/apply upsert orchestration on top of ``AnkiFlow``."""

    def __init__(
        self, *, anki_flow: AnkiFlow, dispatch: Dispatch = call_inline
    ) -> None:
        self._anki_flow = anki_flow
        self._dispatch = dispatch
        self._prepare_future: Future[AnkiUpsertPreviewResult] | None = None
        self._apply_future: Future[AnkiResult] | None = None
        self._anki_request_id: int | None = None

    def cancel_pending(self) -> None:
        if self._prepare_future is not None:
            self._prepare_future.cancel()
        if self._apply_future is not None:
            self._apply_future.cancel()

    def is_config_ready(self, config: AnkiConfig) -> bool:
        return self._anki_flow.is_config_ready(config)

    def prepare_upsert(
        self,
        *,
        request_id: int,
        config: AnkiConfig,
        original_text: str,
        result: TranslationResult,
        examples_override: tuple[str, ...] | None,
        is_request_active: Callable[[int], bool],
        on_ready: Callable[[AnkiUpsertPreview], None],
        set_anki_available: Callable[[bool], None],
        notify: Callable[[Notification], None],
    ) -> None:
        if self._prepare_future is not None:
            self._prepare_future.cancel()
        self._anki_request_id = request_id
        future = self._anki_flow.prepare_upsert(
            config,
            original_text,
            result,
            examples_override=examples_override,
        )
        future.add_done_callback(
            lambda done: self._dispatch(
                lambda: self._apply_prepare_result(
                    request_id,
                    done,
                    is_request_active,
                    on_ready,
                    set_anki_available,
                    notify,
                )
            )
        )
        self._prepare_future = future

    def apply_upsert(
        self,
        *,
        request_id: int,
        config: AnkiConfig,
        original_text: str,
        preview: AnkiUpsertPreview,
        decision: AnkiUpsertDecision,
        is_request_active: Callable[[int], bool],
        on_success: Callable[[], None],
        on_updated: Callable[[], None],
        on_unchanged: Callable[[], None],
        set_anki_available: Callable[[bool], None],
        notify: Callable[[Notification], None],
    ) -> None:
        if self._apply_future is not None:
            self._apply_future.cancel()
        self._anki_request_id = request_id
        future = self._anki_flow.apply_upsert(
            config=config,
            original_text=original_text,
            preview=preview,
            decision=decision,
        )
        future.add_done_callback(
            lambda done: self._dispatch(
                lambda: self._apply_upsert_result(
                    request_id,
                    done,
                    is_request_active,
                    on_success,
                    on_updated,
                    on_unchanged,
                    set_anki_available,
                    notify,
                )
            )
        )
        self._apply_future = future

    def refresh_decks(
        self,
        *,
        update_availability: bool,
        set_anki_available: Callable[[bool], None],
    ) -> None:
        future = self._anki_flow.refresh_decks()
        future.add_done_callback(
            lambda done_future: self._dispatch(
                lambda: self._apply_anki_lists(
                    done_future,
                    update_availability,
                    set_anki_available,
                )
            )
        )

    def _apply_prepare_result(
        self,
        request_id: int,
        future: Future[AnkiUpsertPreviewResult],
        is_request_active: Callable[[int], bool],
        on_ready: Callable[[AnkiUpsertPreview], None],
        set_anki_available: Callable[[bool], None],
        notify: Callable[[Notification], None],
    ) -> None:
        del set_anki_available
        if request_id != self._anki_request_id or not is_request_active(request_id):
            return
        if future.cancelled():
            return
        try:
            result = future.result()
        except Exception as exc:
            notify(notify_messages.anki_error(str(exc) or "Failed to prepare upsert."))
            return
        if result.error is not None:
            if result.error.outcome is AnkiOutcome.UNAVAILABLE:
                notify(notify_messages.anki_unavailable())
                return
            if result.error.outcome is AnkiOutcome.DUPLICATE:
                notify(notify_messages.anki_duplicate())
                return
            notify(
                notify_messages.anki_error(
                    result.error.message or "Failed to prepare upsert."
                )
            )
            return
        if result.preview is None:
            notify(notify_messages.anki_error("Failed to prepare upsert."))
            return
        on_ready(result.preview)

    def _apply_upsert_result(
        self,
        request_id: int,
        future: Future[AnkiResult],
        is_request_active: Callable[[int], bool],
        on_success: Callable[[], None],
        on_updated: Callable[[], None],
        on_unchanged: Callable[[], None],
        set_anki_available: Callable[[bool], None],
        notify: Callable[[Notification], None],
    ) -> None:
        del set_anki_available
        if request_id != self._anki_request_id or not is_request_active(request_id):
            return
        if future.cancelled():
            return
        try:
            result = future.result()
        except Exception as exc:
            notify(notify_messages.anki_error(str(exc) or "Failed to process upsert."))
            return
        if result.outcome is AnkiOutcome.SUCCESS:
            on_success()
            return
        if result.outcome is AnkiOutcome.UPDATED:
            on_updated()
            return
        if result.outcome is AnkiOutcome.UNCHANGED:
            on_unchanged()
            return
        if result.outcome is AnkiOutcome.DUPLICATE:
            notify(notify_messages.anki_duplicate())
            return
        if result.outcome is AnkiOutcome.UNAVAILABLE:
            notify(notify_messages.anki_unavailable())
            return
        notify(notify_messages.anki_error(result.message or "Failed to add card."))

    def _apply_anki_lists(
        self,
        future: Future[AnkiListResult],
        update_availability: bool,
        set_anki_available: Callable[[bool], None],
    ) -> None:
        if future.cancelled():
            return
        try:
            deck_result = future.result()
        except Exception:
            return
        if update_availability:
            set_anki_available(deck_result.error is None)
