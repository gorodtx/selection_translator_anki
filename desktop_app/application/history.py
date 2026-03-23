from __future__ import annotations

from dataclasses import dataclass

from desktop_app.application.examples_state import EntryExamplesState
from translate_logic.models import TranslationResult


@dataclass(frozen=True, slots=True)
class HistoryItem:
    entry_id: int
    text: str
    lookup_text: str
    result: TranslationResult
    examples_state: EntryExamplesState
