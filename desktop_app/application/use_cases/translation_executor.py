from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.application.examples_state import EntryExamplesState
from desktop_app.application.history import HistoryItem
from desktop_app.application.use_cases.translation_flow import TranslationFlow
from desktop_app.application.translation_session import TranslationSession
from desktop_app.config import AppConfig
from translate_logic.models import Example
from translate_logic.models import TranslationResult


@dataclass(frozen=True, slots=True)
class PreparedTranslation:
    display_text: str
    network_text: str
    lookup_text: str
    cached: TranslationResult | None


@dataclass(slots=True)
class TranslationExecutor:
    flow: TranslationFlow
    config: AppConfig

    def update_config(self, config: AppConfig) -> None:
        self.config = config

    def history_snapshot(self) -> list[HistoryItem]:
        return self.flow.snapshot_history()

    def history_entry(self, text: str) -> HistoryItem | None:
        return self.flow.history_entry(text)

    def prepare(self, text: str) -> PreparedTranslation | None:
        languages = self.config.languages
        outcome = self.flow.prepare(text, languages.source, languages.target)
        if (
            outcome.display_text is None
            or outcome.network_text is None
            or outcome.lookup_text is None
            or outcome.error is not None
        ):
            return None
        cached = self.flow.get_cached(
            outcome.network_text,
            languages.source,
            languages.target,
        )
        return PreparedTranslation(
            display_text=outcome.display_text,
            network_text=outcome.network_text,
            lookup_text=outcome.lookup_text,
            cached=cached,
        )

    def register_result(
        self,
        display_text: str,
        lookup_text: str,
        result: TranslationResult,
    ) -> HistoryItem | None:
        return self.flow.register_result(display_text, lookup_text, result)

    def refresh_examples(
        self,
        lookup_text: str,
        *,
        limit: int,
    ) -> Future[tuple[Example, ...]]:
        return self.flow.refresh_examples(lookup_text, limit=limit)

    def update_entry_examples(
        self,
        entry_id: int,
        examples_state: EntryExamplesState,
    ) -> HistoryItem | None:
        return self.flow.update_entry_examples(entry_id, examples_state)

    def run(
        self,
        display_text: str,
        network_text: str,
        lookup_text: str,
        *,
        on_start: Callable[[str], None],
        on_partial: Callable[[TranslationResult], None],
        on_complete: Callable[[TranslationResult], None],
        on_error: Callable[[], None],
    ) -> Future[TranslationResult]:
        languages = self.config.languages

        def start_translation(
            text: str,
            lookup: str,
            on_partial_result: Callable[[TranslationResult], None],
        ) -> Future[TranslationResult]:
            return self.flow.translate(
                text,
                lookup,
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
        return session.run(display_text, network_text, lookup_text)
