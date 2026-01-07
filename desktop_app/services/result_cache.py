from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import time

from translate_logic.models import TranslationResult


@dataclass(frozen=True, slots=True)
class _ResultEntry:
    value: TranslationResult
    expires_at: float


def _default_items() -> OrderedDict[str, _ResultEntry]:
    return OrderedDict()


@dataclass(slots=True)
class ResultCache:
    max_entries: int = 512
    ttl_seconds: float = 3600.0
    _items: OrderedDict[str, _ResultEntry] = field(default_factory=_default_items)

    def get(self, key: str) -> TranslationResult | None:
        now = time.monotonic()
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= now:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return entry.value

    def set(self, key: str, value: TranslationResult) -> None:
        now = time.monotonic()
        expires_at = now + self.ttl_seconds
        self._purge_expired(now)
        self._items[key] = _ResultEntry(value=value, expires_at=expires_at)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def _purge_expired(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._items.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            del self._items[key]
