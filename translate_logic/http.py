from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import aiohttp

from translate_logic.cache import Cache

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; Win64; x64)"

AsyncFetcher = Callable[[str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class FetchError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


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
) -> AsyncFetcher:
    async def fetch(url: str) -> str:
        if cache is not None:
            cached = cache.get(url)
            if cached is not None:
                return cached
        payload = await fetch_text_async(url, session, timeout)
        if cache is not None:
            cache.set(url, payload)
        return payload

    return fetch
