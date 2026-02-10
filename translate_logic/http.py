from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Awaitable, Callable
from urllib.parse import urlparse

import aiohttp

from translate_logic.cache import Cache

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_FAILURE_BACKOFF_SECONDS = 30.0
MAX_FAILURE_BACKOFF_ENTRIES = 1024
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; Win64; x64)"

AsyncFetcher = Callable[[str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class FetchError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class FailureBackoffStore:
    ttl_seconds: float
    max_entries: int
    _backoff_until: dict[str, float] = field(default_factory=dict)

    def should_backoff(self, url: str) -> bool:
        now = time.monotonic()
        self._purge_expired(now)
        blocked_until = self._backoff_until.get(url)
        return blocked_until is not None and blocked_until > now

    def mark_failure(self, url: str) -> None:
        now = time.monotonic()
        self._purge_expired(now)
        self._backoff_until[url] = now + self.ttl_seconds
        while len(self._backoff_until) > self.max_entries:
            oldest_key = next(iter(self._backoff_until))
            del self._backoff_until[oldest_key]

    def clear(self, url: str) -> None:
        self._backoff_until.pop(url, None)

    def _purge_expired(self, now: float) -> None:
        expired = [
            url
            for url, blocked_until in self._backoff_until.items()
            if blocked_until <= now
        ]
        for url in expired:
            del self._backoff_until[url]


async def fetch_text_async(
    url: str,
    session: aiohttp.ClientSession,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    timeout_config = aiohttp.ClientTimeout(total=timeout)
    try:
        async with session.get(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=timeout_config,
        ) as response:
            return await response.text(errors="replace")
    except Exception as exc:
        raise FetchError(f"Failed to fetch {url}") from exc


def build_async_fetcher(
    session: aiohttp.ClientSession,
    cache: Cache | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    *,
    timeouts_by_host: dict[str, float] | None = None,
    timeouts_by_pattern: tuple[tuple[str, float], ...] | None = None,
    failure_backoff_seconds: float = DEFAULT_FAILURE_BACKOFF_SECONDS,
    failure_backoff_store: FailureBackoffStore | None = None,
) -> AsyncFetcher:
    backoff_store = failure_backoff_store
    if backoff_store is None and failure_backoff_seconds > 0:
        backoff_store = FailureBackoffStore(
            ttl_seconds=failure_backoff_seconds,
            max_entries=MAX_FAILURE_BACKOFF_ENTRIES,
        )

    async def fetch(url: str) -> str:
        if cache is not None:
            cached = cache.get(url)
            if cached is not None:
                return cached
        if backoff_store is not None and backoff_store.should_backoff(url):
            raise FetchError(f"Failed to fetch {url}")
        effective_timeout = _resolve_timeout(
            url,
            timeout,
            timeouts_by_host,
            timeouts_by_pattern,
        )
        try:
            payload = await fetch_text_async(url, session, effective_timeout)
        except FetchError:
            if backoff_store is not None:
                backoff_store.mark_failure(url)
            raise
        if backoff_store is not None:
            backoff_store.clear(url)
        if cache is not None:
            cache.set(url, payload)
        return payload

    return fetch


def _resolve_timeout(
    url: str,
    default_timeout: float,
    timeouts_by_host: dict[str, float] | None,
    timeouts_by_pattern: tuple[tuple[str, float], ...] | None,
) -> float:
    if timeouts_by_pattern is not None:
        for pattern, pattern_timeout in timeouts_by_pattern:
            if pattern and pattern in url and pattern_timeout > 0:
                return pattern_timeout
    if timeouts_by_host is None:
        return default_timeout
    host = urlparse(url).hostname
    if host is None:
        return default_timeout
    configured_timeout = timeouts_by_host.get(host)
    if configured_timeout is None or configured_timeout <= 0:
        return default_timeout
    return configured_timeout
