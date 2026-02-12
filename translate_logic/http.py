from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit

import aiohttp

from translate_logic.cache import HttpCache, HttpCacheStats, ProviderKind

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_FAILURE_BACKOFF_SECONDS = 30.0
MAX_FAILURE_BACKOFF_ENTRIES = 1024
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; Win64; x64)"
_NOISE_QUERY_KEYS = frozenset({"client", "version", "v"})

AsyncFetcher = Callable[[str], Awaitable[str]]


class FetchError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class FetchTimeoutError(FetchError):
    pass


class FetchStatusError(FetchError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class FailureBackoffStore:
    def __init__(self, ttl_seconds: float, max_entries: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._backoff_until: dict[str, float] = {}

    def should_backoff(self, key: str) -> bool:
        now = time.monotonic()
        self._purge_expired(now)
        blocked_until = self._backoff_until.get(key)
        return blocked_until is not None and blocked_until > now

    def mark_failure(self, key: str) -> None:
        now = time.monotonic()
        self._purge_expired(now)
        self._backoff_until[key] = now + self.ttl_seconds
        while len(self._backoff_until) > self.max_entries:
            oldest_key = next(iter(self._backoff_until))
            del self._backoff_until[oldest_key]

    def clear(self, key: str) -> None:
        self._backoff_until.pop(key, None)

    def _purge_expired(self, now: float) -> None:
        expired = [
            key
            for key, blocked_until in self._backoff_until.items()
            if blocked_until <= now
        ]
        for key in expired:
            del self._backoff_until[key]


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
            payload = await response.text(errors="replace")
            if response.status == 429:
                raise FetchStatusError(f"Failed to fetch {url}", status_code=429)
            return payload
    except FetchStatusError:
        raise
    except asyncio.TimeoutError as exc:
        raise FetchTimeoutError(f"Failed to fetch {url}") from exc
    except Exception as exc:
        raise FetchError(f"Failed to fetch {url}") from exc


def build_async_fetcher(
    session: aiohttp.ClientSession,
    cache: HttpCache | None = None,
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
    in_flight: dict[str, asyncio.Task[str]] = {}

    async def fetch(url: str) -> str:
        key = normalize_url_cache_key(url)
        if cache is not None:
            cached = cache.get_fresh(key)
            if cached is not None:
                return cached
            if cache.is_negative_blocked(key):
                stale = cache.get_stale(key)
                if stale is not None:
                    return stale
                raise FetchError(f"Failed to fetch {url}")
        if backoff_store is not None and backoff_store.should_backoff(key):
            if cache is not None:
                stale = cache.get_stale(key)
                if stale is not None:
                    return stale
            raise FetchError(f"Failed to fetch {url}")

        existing = in_flight.get(key)
        if existing is not None:
            return await existing

        async def _fetch_and_store() -> str:
            effective_timeout = _resolve_timeout(
                url,
                timeout,
                timeouts_by_host,
                timeouts_by_pattern,
            )
            try:
                payload = await fetch_text_async(url, session, effective_timeout)
            except FetchError as exc:
                if backoff_store is not None:
                    backoff_store.mark_failure(key)
                if cache is not None and _is_negative_candidate(exc):
                    cache.set_negative(key)
                    stale = cache.get_stale(key)
                    if stale is not None:
                        return stale
                raise
            if backoff_store is not None:
                backoff_store.clear(key)
            if cache is not None:
                cache.set_success(key, payload, _detect_provider(url))
            return payload

        task = asyncio.create_task(_fetch_and_store())
        in_flight[key] = task
        try:
            return await task
        finally:
            current = in_flight.get(key)
            if current is task:
                del in_flight[key]

    return fetch


def normalize_url_cache_key(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    path = parsed.path
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [
        (key, value) for key, value in pairs if key.casefold() not in _NOISE_QUERY_KEYS
    ]
    filtered.sort(key=lambda item: (item[0], item[1]))
    query = urlencode(filtered, doseq=True)
    if query:
        return f"{host}{path}?{query}"
    return f"{host}{path}"


def get_http_cache_stats(cache: HttpCache | None) -> HttpCacheStats | None:
    if cache is None:
        return None
    return cache.snapshot()


def _detect_provider(url: str) -> ProviderKind:
    host = (urlparse(url).hostname or "").lower()
    if host == "translate.googleapis.com":
        return "google"
    if host == "dictionary.cambridge.org":
        return "cambridge"
    return "unknown"


def _is_negative_candidate(error: FetchError) -> bool:
    if isinstance(error, FetchTimeoutError):
        return True
    if isinstance(error, FetchStatusError):
        return error.status_code == 429
    return isinstance(error, FetchError)


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
