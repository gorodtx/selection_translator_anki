from __future__ import annotations

from dataclasses import dataclass

from translate_logic.domain.models import Example, QueryLimit


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    max_cambridge_words: int = QueryLimit.MAX_CAMBRIDGE_WORDS.value

    def use_cambridge(self, word_count: int) -> bool:
        return word_count <= self.max_cambridge_words

    def needs_dictionary(self, ipa_uk: str | None, examples: list[Example]) -> bool:
        return ipa_uk is None or not examples

    def needs_tatoeba(self, examples: list[Example]) -> bool:
        return not any(example.ru for example in examples)
