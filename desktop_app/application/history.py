from __future__ import annotations

from dataclasses import dataclass

from translate_logic.models import TranslationResult


@dataclass(frozen=True, slots=True)
class HistoryItem:
    text: str
    result: TranslationResult
