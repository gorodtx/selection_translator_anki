from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from desktop_app.application.history import HistoryItem
from translate_logic.models import TranslationResult

DEFAULT_HISTORY_MAX_ENTRIES: Final[int] = 100


def _default_items() -> list[HistoryItem]:
    return []


@dataclass(slots=True)
class HistoryStore:
    max_entries: int = DEFAULT_HISTORY_MAX_ENTRIES
    _items: list[HistoryItem] = field(default_factory=_default_items)

    def add(self, text: str, result: TranslationResult) -> None:
        if any(item.text == text for item in self._items):
            return
        self._items.append(
            HistoryItem(
                text=text,
                result=result,
            )
        )
        while len(self._items) > self.max_entries:
            self._items.pop(0)

    def snapshot(self) -> list[HistoryItem]:
        return list(reversed(self._items))
