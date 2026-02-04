from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.application.history import HistoryItem
from desktop_app.application.ports import HistoryPort, TranslatorPort
from desktop_app.application.query import QueryOutcome, prepare_query
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
        query_text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]:
        return self.translator.translate(
            query_text, source_lang, target_lang, on_partial=on_partial
        )

    def cached_result(
        self, query_text: str, source_lang: str, target_lang: str
    ) -> TranslationResult | None:
        return self.translator.cached(query_text, source_lang, target_lang)

    def register_result(self, display_text: str, result: TranslationResult) -> None:
        if result.status is not TranslationStatus.SUCCESS:
            return
        self.history.add(display_text, result)

    def snapshot_history(self) -> list[HistoryItem]:
        return self.history.snapshot()
