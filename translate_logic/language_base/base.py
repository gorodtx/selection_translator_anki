from __future__ import annotations

from typing import Protocol

from translate_logic.models import ExamplePair


class LanguageBase(Protocol):
    @property
    def is_available(self) -> bool: ...

    def get_examples(
        self, *, word: str, translation: str, limit: int
    ) -> tuple[ExamplePair, ...]: ...

    def get_variants(self, *, word: str, limit: int) -> tuple[str, ...]: ...
