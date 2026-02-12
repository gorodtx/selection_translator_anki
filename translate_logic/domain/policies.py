from __future__ import annotations

from dataclasses import dataclass

from translate_logic.domain.models import QueryLimit


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    max_cambridge_words: int = QueryLimit.MAX_CAMBRIDGE_WORDS.value

    def use_cambridge(self, word_count: int) -> bool:
        return word_count <= self.max_cambridge_words
