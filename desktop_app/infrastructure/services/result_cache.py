from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from translate_logic.models import TranslationResult


@dataclass(frozen=True, slots=True)
class _ResultEntry:
    value: TranslationResult


def _default_items() -> OrderedDict[str, _ResultEntry]:
    return OrderedDict()


@dataclass(slots=True)
class ResultCache:
    max_entries: int = 100
    _items: OrderedDict[str, _ResultEntry] = field(default_factory=_default_items)

    def get(self, key: str) -> TranslationResult | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        self._items.move_to_end(key)
        return entry.value

    def set(self, key: str, value: TranslationResult) -> None:
        self._items[key] = _ResultEntry(value=value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def delete(self, key: str) -> None:
        if key in self._items:
            self._items.pop(key, None)
