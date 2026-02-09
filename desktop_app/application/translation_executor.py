from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.application.history import HistoryItem
from desktop_app.application.translation_flow import TranslationFlow
from desktop_app.application.translation_session import TranslationSession
from desktop_app.config import AppConfig
from translate_logic.models import TranslationResult


@dataclass(frozen=True, slots=True)
class PreparedTranslation:
    display_text: str
    query_text: str
    cached: TranslationResult | None


@dataclass(slots=True)
class TranslationExecutor:
    flow: TranslationFlow
    config: AppConfig

    def update_config(self, config: AppConfig) -> None:
        self.config = config

    def history_snapshot(self) -> list[HistoryItem]:
        return self.flow.snapshot_history()

    def prepare(self, text: str) -> PreparedTranslation | None:
        languages = self.config.languages
        outcome = self.flow.prepare(text, languages.source, languages.target)
        if (
            outcome.display_text is None
            or outcome.query_text is None
            or outcome.error is not None
        ):
            return None
        return PreparedTranslation(
            display_text=outcome.display_text,
            query_text=outcome.query_text,
            cached=None,
        )

    def register_result(self, display_text: str, result: TranslationResult) -> None:
        self.flow.register_result(display_text, result)

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
        languages = self.config.languages

        def start_translation(
            query: str, on_partial_result: Callable[[TranslationResult], None]
        ) -> Future[TranslationResult]:
            return self.flow.translate(
                query,
                languages.source,
                languages.target,
                on_partial=on_partial_result,
            )

        session = TranslationSession(
            start_translation=start_translation,
            on_start=on_start,
            on_partial=on_partial,
            on_complete=on_complete,
            on_error=on_error,
        )
        return session.run(display_text, query_text)
