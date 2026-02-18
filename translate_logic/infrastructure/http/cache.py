from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import time
from typing import Literal

ProviderKind = Literal["google", "cambridge", "unknown"]


@dataclass(frozen=True, slots=True)
class HttpCachePolicy:
    max_entries: int = 256
    max_bytes: int = 32 * 1024 * 1024
    google_ttl_s: float = 90.0
    cambridge_ttl_s: float = 300.0
    unknown_ttl_s: float = 90.0
    negative_ttl_s: float = 30.0
    max_stale_if_error_s: float = 600.0
    max_value_chars: int = 250_000


@dataclass(frozen=True, slots=True)
class HttpCacheStats:
    hits_fresh: int
    hits_stale: int
    misses: int
    negative_hits: int
    evictions_count: int
    bytes_current: int
    bytes_peak: int
    avg_payload_bytes: float


@dataclass(frozen=True, slots=True)
class HttpCacheEntry:
    payload: str
    size_bytes: int
    fresh_until: float
    stale_until: float
    provider: ProviderKind


def _default_items() -> OrderedDict[str, HttpCacheEntry]:
    return OrderedDict()


def _default_negative() -> dict[str, float]:
    return {}


@dataclass(slots=True)
class HttpCache:
    policy: HttpCachePolicy = field(default_factory=HttpCachePolicy)
    _items: OrderedDict[str, HttpCacheEntry] = field(default_factory=_default_items)
    _negative_until: dict[str, float] = field(default_factory=_default_negative)
    _bytes_current: int = 0
    _bytes_peak: int = 0
    _hits_fresh: int = 0
    _hits_stale: int = 0
    _misses: int = 0
    _negative_hits: int = 0
    _evictions_count: int = 0
    _stored_payload_count: int = 0
    _stored_payload_total_bytes: int = 0

    def get_fresh(self, key: str) -> str | None:
        now = time.monotonic()
        self._purge_expired(now)
        entry = self._items.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.fresh_until <= now:
            self._misses += 1
            return None
        self._items.move_to_end(key)
        self._hits_fresh += 1
        return entry.payload

    def get_stale(self, key: str) -> str | None:
        now = time.monotonic()
        self._purge_expired(now)
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.stale_until <= now:
            return None
        self._items.move_to_end(key)
        self._hits_stale += 1
        return entry.payload

    def set_success(self, key: str, payload: str, provider: ProviderKind) -> None:
        if len(payload) > self.policy.max_value_chars:
            return
        now = time.monotonic()
        self._purge_expired(now)
        ttl = self._ttl_for_provider(provider)
        size_bytes = len(payload.encode("utf-8", errors="replace"))
        if size_bytes > self.policy.max_bytes:
            return
        previous = self._items.pop(key, None)
        if previous is not None:
            self._bytes_current -= previous.size_bytes
        entry = HttpCacheEntry(
            payload=payload,
            size_bytes=size_bytes,
            fresh_until=now + ttl,
            stale_until=now + ttl + self.policy.max_stale_if_error_s,
            provider=provider,
        )
        self._items[key] = entry
        self._items.move_to_end(key)
        self._bytes_current += size_bytes
        if self._bytes_current > self._bytes_peak:
            self._bytes_peak = self._bytes_current
        self._stored_payload_count += 1
        self._stored_payload_total_bytes += size_bytes
        self._negative_until.pop(key, None)
        self._evict_to_budget()

    def set_negative(self, key: str) -> None:
        now = time.monotonic()
        self._purge_expired(now)
        self._negative_until[key] = now + self.policy.negative_ttl_s

    def is_negative_blocked(self, key: str) -> bool:
        now = time.monotonic()
        self._purge_expired(now)
        blocked_until = self._negative_until.get(key)
        if blocked_until is None or blocked_until <= now:
            return False
        self._negative_hits += 1
        return True

    def snapshot(self) -> HttpCacheStats:
        avg_payload_bytes = 0.0
        if self._stored_payload_count > 0:
            avg_payload_bytes = (
                self._stored_payload_total_bytes / self._stored_payload_count
            )
        return HttpCacheStats(
            hits_fresh=self._hits_fresh,
            hits_stale=self._hits_stale,
            misses=self._misses,
            negative_hits=self._negative_hits,
            evictions_count=self._evictions_count,
            bytes_current=self._bytes_current,
            bytes_peak=self._bytes_peak,
            avg_payload_bytes=avg_payload_bytes,
        )

    def _ttl_for_provider(self, provider: ProviderKind) -> float:
        if provider == "google":
            return self.policy.google_ttl_s
        if provider == "cambridge":
            return self.policy.cambridge_ttl_s
        return self.policy.unknown_ttl_s

    def _purge_expired(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._items.items() if entry.stale_until <= now
        ]
        for key in expired_keys:
            entry = self._items.pop(key)
            self._bytes_current -= entry.size_bytes
        expired_negative = [
            key
            for key, blocked_until in self._negative_until.items()
            if blocked_until <= now
        ]
        for key in expired_negative:
            del self._negative_until[key]
        if self._bytes_current < 0:
            self._bytes_current = 0

    def _evict_to_budget(self) -> None:
        while (
            len(self._items) > self.policy.max_entries
            or self._bytes_current > self.policy.max_bytes
        ):
            _, entry = self._items.popitem(last=False)
            self._bytes_current -= entry.size_bytes
            self._evictions_count += 1
        if self._bytes_current < 0:
            self._bytes_current = 0
