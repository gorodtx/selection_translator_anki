from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import time
from typing import Final

from desktop_app.application.history import HistoryItem
from translate_logic.models import TranslationResult

DEFAULT_HISTORY_MAX_ENTRIES: Final[int] = 512
DEFAULT_HISTORY_TTL_SECONDS: Final[float] = 3600.0


def _default_items() -> OrderedDict[str, HistoryItem]:
    return OrderedDict()


@dataclass(slots=True)
class HistoryStore:
    max_entries: int = DEFAULT_HISTORY_MAX_ENTRIES
    ttl_seconds: float = DEFAULT_HISTORY_TTL_SECONDS
    _items: OrderedDict[str, HistoryItem] = field(default_factory=_default_items)

    def add(self, text: str, result: TranslationResult) -> None:
        now = time.monotonic()
        expires_at = now + self.ttl_seconds
        self._purge_expired(now)
        self._items[text] = HistoryItem(
            text=text,
            result=result,
            expires_at=expires_at,
        )
        self._items.move_to_end(text)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def snapshot(self) -> list[HistoryItem]:
        now = time.monotonic()
        self._purge_expired(now)
        return list(reversed(self._items.values()))

    def _purge_expired(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._items.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            del self._items[key]
