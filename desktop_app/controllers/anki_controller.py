from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
import importlib

from desktop_app.anki import AnkiAddResult, AnkiListResult
from desktop_app.application.anki_flow import AnkiFlow, AnkiOutcome, AnkiResult
from desktop_app.config import AnkiConfig
from desktop_app.notifications import Notification
from desktop_app.notifications import messages as notify_messages
from translate_logic.models import TranslationResult

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("GLib", "2.0")
GLib = importlib.import_module("gi.repository.GLib")


class AnkiController:
    def __init__(self, *, anki_flow: AnkiFlow) -> None:
        self._anki_flow = anki_flow
        self._anki_future: Future[AnkiAddResult] | None = None
        self._anki_request_id: int | None = None

    def cancel_pending(self) -> None:
        if self._anki_future is not None:
            self._anki_future.cancel()

    def is_config_ready(self, config: AnkiConfig) -> bool:
        return self._anki_flow.is_config_ready(config)

    def add_note(
        self,
        *,
        request_id: int,
        config: AnkiConfig,
        original_text: str,
        result: TranslationResult,
        is_request_active: Callable[[int], bool],
        on_success: Callable[[], None],
        set_anki_available: Callable[[bool], None],
        notify: Callable[[Notification], None],
    ) -> None:
        if self._anki_future is not None:
            self._anki_future.cancel()
        self._anki_request_id = request_id

        def on_done(anki_result: AnkiResult) -> None:
            GLib.idle_add(
                self._apply_result,
                request_id,
                anki_result,
                is_request_active,
                on_success,
                set_anki_available,
                notify,
            )

        future = self._anki_flow.add_note(
            config,
            original_text,
            result,
            on_done=on_done,
            on_unavailable=lambda: set_anki_available(False),
        )
        self._anki_future = future

    def refresh_decks(
        self,
        *,
        update_availability: bool,
        set_anki_available: Callable[[bool], None],
    ) -> None:
        future = self._anki_flow.refresh_decks()
        future.add_done_callback(
            lambda done_future: GLib.idle_add(
                self._apply_anki_lists,
                done_future,
                update_availability,
                set_anki_available,
            )
        )

    def _apply_result(
        self,
        request_id: int,
        result: AnkiResult,
        is_request_active: Callable[[int], bool],
        on_success: Callable[[], None],
        set_anki_available: Callable[[bool], None],
        notify: Callable[[Notification], None],
    ) -> bool:
        if request_id != self._anki_request_id or not is_request_active(request_id):
            return False
        if result.outcome is AnkiOutcome.SUCCESS:
            on_success()
            return False
        if result.outcome is AnkiOutcome.DUPLICATE:
            notify(notify_messages.anki_duplicate())
            return False
        if result.outcome is AnkiOutcome.UNAVAILABLE:
            notify(notify_messages.anki_unavailable())
            set_anki_available(False)
            return False
        notify(notify_messages.anki_error(result.message or "Failed to add card."))
        return False

    def _apply_anki_lists(
        self,
        future: Future[AnkiListResult],
        update_availability: bool,
        set_anki_available: Callable[[bool], None],
    ) -> bool:
        if future.cancelled():
            return False
        try:
            deck_result = future.result()
        except Exception:
            return False
        if update_availability:
            set_anki_available(deck_result.error is None)
        return False
