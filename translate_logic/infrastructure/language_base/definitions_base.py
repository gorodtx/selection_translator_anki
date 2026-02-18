from __future__ import annotations

from typing import Protocol


class DefinitionsBase(Protocol):
    @property
    def is_available(self) -> bool: ...

    def get_definitions(self, *, word: str, limit: int) -> tuple[str, ...]: ...

    def warmup(self) -> None: ...
