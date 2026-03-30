from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.application.examples_state import EntryExamplesState
from desktop_app.application.history import HistoryItem
from desktop_app.application.ports.interfaces import HistoryPort, TranslatorPort
from desktop_app.application.query import QueryOutcome, prepare_query
from translate_logic.models import Example
from translate_logic.models import TranslationResult, TranslationStatus


@dataclass(slots=True)
class TranslationFlow:
    translator: TranslatorPort
    history: HistoryPort

    def prepare(
        self, raw_text: str, source_lang: str, target_lang: str
    ) -> QueryOutcome:
        return prepare_query(raw_text, source_lang, target_lang)

    def translate(
        self,
        text: str,
        lookup_text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]:
        return self.translator.translate(
            text,
            lookup_text,
            source_lang,
            target_lang,
            on_partial=on_partial,
        )

    def get_cached(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult | None:
        return self.translator.get_cached(text, source_lang, target_lang)

    def refresh_examples(
        self,
        lookup_text: str,
        *,
        limit: int,
    ) -> Future[tuple[Example, ...]]:
        return self.translator.refresh_examples(lookup_text, limit=limit)

    def register_result(
        self,
        display_text: str,
        lookup_text: str,
        result: TranslationResult,
    ) -> HistoryItem | None:
        if result.status is not TranslationStatus.SUCCESS:
            return None
        return self.history.add(display_text, lookup_text, result)

    def history_entry(self, text: str) -> HistoryItem | None:
        return self.history.find_by_text(text)

    def update_entry_examples(
        self,
        entry_id: int,
        examples_state: EntryExamplesState,
    ) -> HistoryItem | None:
        return self.history.update_examples(entry_id, examples_state)

    def snapshot_history(self) -> list[HistoryItem]:
        return self.history.snapshot()
