from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.application.history import HistoryItem
from desktop_app.application.translation_flow import TranslationFlow
from desktop_app.application.translation_session import TranslationSession
from desktop_app.config import AppConfig
from translate_logic.models import TranslationResult


@dataclass(slots=True)
class PreparedTranslation:
    display_text: str
    query_text: str
    cached: TranslationResult | None


class TranslationExecutor:
    def __init__(self, *, flow: TranslationFlow, config: AppConfig) -> None:
        self._flow = flow
        self._config = config

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def prepare(self, text: str) -> PreparedTranslation | None:
        outcome = self._flow.prepare(
            text,
            self._config.languages.source,
            self._config.languages.target,
        )
        if outcome.error is not None:
            return None
        if outcome.display_text is None or outcome.query_text is None:
            return None
        cached = self._flow.cached_result(
            outcome.query_text,
            self._config.languages.source,
            self._config.languages.target,
        )
        return PreparedTranslation(
            display_text=outcome.display_text,
            query_text=outcome.query_text,
            cached=cached,
        )

    def run(
        self,
        display_text: str,
        query_text: str,
        *,
        on_start: Callable[[str], None],
        on_partial: Callable[[TranslationResult], None],
        on_complete: Callable[[TranslationResult], None],
        on_error: Callable[[], None],
    ) -> Future[TranslationResult]:
        def start_translation(
            query: str, on_partial_callback: Callable[[TranslationResult], None]
        ) -> Future[TranslationResult]:
            return self._flow.translate(
                query,
                self._config.languages.source,
                self._config.languages.target,
                on_partial=on_partial_callback,
            )

        session = TranslationSession(
            start_translation=start_translation,
            on_start=on_start,
            on_partial=on_partial,
            on_complete=on_complete,
            on_error=on_error,
        )
        return session.run(display_text, query_text)

    def register_result(self, display_text: str, result: TranslationResult) -> None:
        self._flow.register_result(display_text, result)

    def history_snapshot(self) -> list[HistoryItem]:
        return self._flow.snapshot_history()
