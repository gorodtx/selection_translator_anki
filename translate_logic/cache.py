from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Protocol


class CacheLimit(Enum):
    MAX_ENTRIES = 512
    TTL_SECONDS = 3600.0


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


@dataclass(slots=True)
class _CacheEntry:
    value: str
    expires_at: float


def _default_items() -> OrderedDict[str, _CacheEntry]:
    return OrderedDict()


@dataclass(slots=True)
class LruTtlCache:
    max_entries: int = CacheLimit.MAX_ENTRIES.value
    ttl_seconds: float = CacheLimit.TTL_SECONDS.value
    _items: OrderedDict[str, _CacheEntry] = field(default_factory=_default_items)

    def get(self, key: str) -> str | None:
        now = time.monotonic()
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= now:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return entry.value

    def set(self, key: str, value: str) -> None:
        now = time.monotonic()
        expires_at = now + self.ttl_seconds
        self._purge_expired(now)
        self._items[key] = _CacheEntry(value=value, expires_at=expires_at)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def _purge_expired(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._items.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            del self._items[key]
