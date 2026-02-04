from __future__ import annotations

from dataclasses import dataclass

from translate_logic.language_base.base import LanguageBase
from translate_logic.language_base.provider import LanguageBaseProvider
from translate_logic.models import ExamplePair


@dataclass(slots=True)
class MultiLanguageBaseProvider(LanguageBase):
    primary: LanguageBaseProvider
    fallback: LanguageBaseProvider

    @property
    def is_available(self) -> bool:
        return self.primary.is_available or self.fallback.is_available

    def get_examples(
        self, *, word: str, translation: str, limit: int
    ) -> tuple[ExamplePair, ...]:
        if limit <= 0:
            return ()
        primary = self.primary.get_examples(
            word=word, translation=translation, limit=limit
        )
        if len(primary) >= limit:
            return primary[:limit]
        needed = limit - len(primary)
        extra = self.fallback.get_examples(
            word=word, translation=translation, limit=limit * 2
        )
        merged: list[ExamplePair] = list(primary)
        for pair in extra:
            if len(merged) >= limit:
                break
            if pair in merged:
                continue
            merged.append(pair)
        if len(merged) >= needed:
            return tuple(merged[:limit])
        return tuple(merged)

    def get_variants(self, *, word: str, limit: int) -> tuple[str, ...]:
        if limit <= 0:
            return ()
        primary = self.primary.get_variants(word=word, limit=limit)
        if len(primary) >= limit:
            return primary[:limit]
        extra = self.fallback.get_variants(word=word, limit=limit * 2)
        merged: list[str] = list(primary)
        seen = {item.casefold() for item in merged}
        for item in extra:
            if len(merged) >= limit:
                break
            folded = item.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            merged.append(item)
        return tuple(merged[:limit])
