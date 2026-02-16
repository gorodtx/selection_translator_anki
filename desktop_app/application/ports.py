from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Protocol

from desktop_app.application.history import HistoryItem
from desktop_app.anki import (
    AnkiAddResult,
    AnkiCreateModelResult,
    AnkiIdListResult,
    AnkiListResult,
    AnkiNoteDetailsResult,
    AnkiUpdateResult,
)
from translate_logic.models import TranslationResult


class TranslatorPort(Protocol):
    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]: ...


class HistoryPort(Protocol):
    def add(self, text: str, result: TranslationResult) -> None: ...

    def snapshot(self) -> list[HistoryItem]: ...


class AnkiPort(Protocol):
    def deck_names(self) -> Future[AnkiListResult]: ...

    def model_names(self) -> Future[AnkiListResult]: ...

    def find_notes(self, query: str) -> Future[AnkiIdListResult]: ...

    def note_details(self, note_ids: list[int]) -> Future[AnkiNoteDetailsResult]: ...

    def add_note(
        self, deck: str, model: str, fields: dict[str, str]
    ) -> Future[AnkiAddResult]: ...

    def update_note_fields(
        self, note_id: int, fields: dict[str, str]
    ) -> Future[AnkiUpdateResult]: ...

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]: ...
