from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field

import aiohttp

from desktop_app.services.result_cache import ResultCache
from desktop_app.services.runtime import AsyncRuntime
from translate_logic.cache import LruTtlCache
from translate_logic.application.translate import translate_async
from translate_logic.http import AsyncFetcher, build_async_fetcher
from translate_logic.models import TranslationResult, TranslationStatus
from translate_logic.text import normalize_text


def _future_set() -> set[Future[TranslationResult]]:
    return set()


@dataclass(slots=True)
class TranslationService:
    runtime: AsyncRuntime
    result_cache: ResultCache

    timeout_seconds: float = 6.0
    _session: aiohttp.ClientSession | None = None
    _fetcher: AsyncFetcher | None = None
    _session_lock: asyncio.Lock | None = None
    _http_cache: LruTtlCache = field(default_factory=LruTtlCache)
    _active: set[Future[TranslationResult]] = field(default_factory=_future_set)

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]:
        cache_key = _cache_key(text, source_lang, target_lang)
        cached = self.result_cache.get(cache_key)
        if cached is not None:
            future: Future[TranslationResult] = Future()
            future.set_result(cached)
            return future
        coro = self._translate_async(text, source_lang, target_lang, on_partial)
        future = asyncio.run_coroutine_threadsafe(coro, self.runtime.loop)
        self._register_future(future)
        return future

    def warmup(self) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ensure_fetcher(), self.runtime.loop
            )
            future.add_done_callback(lambda done: done.exception())
        except Exception:
            return

    def cancel_active(self) -> None:
        for future in list(self._active):
            future.cancel()
        self._active.clear()
        asyncio.run_coroutine_threadsafe(self._abort_session(), self.runtime.loop)

    async def _translate_async(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None,
    ) -> TranslationResult:
        fetcher = await self._ensure_fetcher()
        emitted = False

        def handle_partial(result: TranslationResult) -> None:
            nonlocal emitted
            if emitted or result.status is not TranslationStatus.SUCCESS:
                return
            emitted = True
            if on_partial is not None:
                on_partial(result)

        result = await translate_async(
            text,
            source_lang,
            target_lang,
            fetcher=fetcher,
            on_partial=handle_partial,
        )
        cache_key = _cache_key(text, source_lang, target_lang)
        if result.status is TranslationStatus.SUCCESS:
            self.result_cache.set(cache_key, result)
        return result

    async def _ensure_fetcher(self) -> AsyncFetcher:
        if self._fetcher is not None and self._session is not None:
            return self._fetcher
        lock = self._session_lock
        if lock is None:
            lock = asyncio.Lock()
            self._session_lock = lock
        async with lock:
            if self._fetcher is not None and self._session is not None:
                return self._fetcher
            self._session = aiohttp.ClientSession()
            self._fetcher = build_async_fetcher(
                self._session,
                cache=self._http_cache,
                timeout=self.timeout_seconds,
            )
            return self._fetcher

    async def close(self) -> None:
        await self._abort_session()

    def _register_future(self, future: Future[TranslationResult]) -> None:
        self._active.add(future)
        future.add_done_callback(self._active.discard)

    async def _abort_session(self) -> None:
        if self._session is None:
            return
        await self._session.close()
        self._session = None
        self._fetcher = None


def _cache_key(text: str, source_lang: str, target_lang: str) -> str:
    normalized = normalize_text(text)
    return f"{source_lang}:{target_lang}:{normalized}"
