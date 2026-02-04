from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Protocol

from desktop_app.application.history import HistoryItem
from desktop_app.anki import AnkiAddResult, AnkiCreateModelResult, AnkiListResult
from translate_logic.models import TranslationResult


class TranslatorPort(Protocol):
    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]: ...

    def cached(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult | None: ...


class HistoryPort(Protocol):
    def add(self, text: str, result: TranslationResult) -> None: ...

    def snapshot(self) -> list[HistoryItem]: ...


class AnkiPort(Protocol):
    def deck_names(self) -> Future[AnkiListResult]: ...

    def model_names(self) -> Future[AnkiListResult]: ...

    def add_note(
        self, deck: str, model: str, fields: dict[str, str]
    ) -> Future[AnkiAddResult]: ...

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]: ...
