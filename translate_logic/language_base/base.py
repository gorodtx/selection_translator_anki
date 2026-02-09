from __future__ import annotations

from typing import Protocol

from translate_logic.models import Example


class LanguageBase(Protocol):
    @property
    def is_available(self) -> bool: ...

    def get_examples(self, *, word: str, limit: int) -> tuple[Example, ...]: ...

    def warmup(self) -> None: ...
