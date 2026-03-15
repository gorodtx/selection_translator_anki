from __future__ import annotations

from dataclasses import dataclass

from translate_logic.infrastructure.language_base.base import LanguageBase
from translate_logic.models import Example


@dataclass(slots=True)
class MultiLanguageBaseProvider(LanguageBase):
    primary: LanguageBase
    fallback: LanguageBase

    @property
    def is_available(self) -> bool:
        return self.primary.is_available or self.fallback.is_available

    def get_examples(self, *, word: str, limit: int) -> tuple[Example, ...]:
        if limit <= 0:
            return ()
        seen: set[str] = set()
        merged: list[Example] = []
        for source in (
            self.primary.get_examples(word=word, limit=limit),
            self.fallback.get_examples(word=word, limit=limit),
        ):
            for example in source:
                key = example.en.strip().casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(example)
                if len(merged) >= limit:
                    return tuple(merged)
        return tuple(merged)

    def warmup(self) -> None:
        self.primary.warmup()
        self.fallback.warmup()
