from __future__ import annotations

from dataclasses import dataclass

from translate_logic.language_base.base import LanguageBase
from translate_logic.language_base.provider import LanguageBaseProvider
from translate_logic.models import Example


@dataclass(slots=True)
class MultiLanguageBaseProvider(LanguageBase):
    primary: LanguageBaseProvider
    fallback: LanguageBaseProvider

    @property
    def is_available(self) -> bool:
        return self.primary.is_available or self.fallback.is_available

    def get_examples(self, *, word: str, limit: int) -> tuple[Example, ...]:
        if limit <= 0:
            return ()
        primary = self.primary.get_examples(word=word, limit=limit)
        if len(primary) >= limit:
            return primary[:limit]
        extra = self.fallback.get_examples(word=word, limit=limit * 2)
        merged: list[Example] = list(primary)
        for pair in extra:
            if len(merged) >= limit:
                break
            if pair in merged:
                continue
            merged.append(pair)
        return tuple(merged[:limit])

    def warmup(self) -> None:
        self.primary.warmup()
        self.fallback.warmup()
