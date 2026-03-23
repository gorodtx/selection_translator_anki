from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
import os
import threading
from typing import cast

import aiohttp

from desktop_app.infrastructure.services.result_cache import ResultCache
from desktop_app.infrastructure.services.runtime import AsyncRuntime
from translate_logic.infrastructure.http.cache import HttpCache
from translate_logic.application.pipeline.translate import (
    build_latency_fetcher,
    filter_examples,
    translate_async,
    warmup_pipeline_resources,
)
from translate_logic.infrastructure.http.transport import AsyncFetcher
from translate_logic.infrastructure.language_base.base import LanguageBase
from translate_logic.infrastructure.language_base.definitions_base import DefinitionsBase
from translate_logic.infrastructure.language_base.definitions_provider import DefinitionsBaseProvider
from translate_logic.infrastructure.language_base.multi_provider import MultiLanguageBaseProvider
from translate_logic.infrastructure.language_base.provider import (
    LanguageBaseProvider,
    default_fallback_language_base_path,
)
from translate_logic.models import Example, TranslationResult, TranslationStatus
from translate_logic.shared.text import normalize_text


def _future_set() -> set[Future[object]]:
    return set()


def _future_map() -> dict[str, Future[TranslationResult]]:
    return {}


def _thread_lock() -> threading.Lock:
    return threading.Lock()


@dataclass(slots=True)
class TranslationService:
    runtime: AsyncRuntime
    result_cache: ResultCache

    _session: aiohttp.ClientSession | None = None
    _fetcher: AsyncFetcher | None = None
    _session_lock: asyncio.Lock | None = None
    _http_cache: HttpCache = field(default_factory=HttpCache)
    _active: set[Future[object]] = field(default_factory=_future_set)
    _inflight: dict[str, Future[TranslationResult]] = field(default_factory=_future_map)
    _state_lock: threading.Lock = field(default_factory=_thread_lock, repr=False)
    _generation: int = 0
    _language_base: LanguageBase = field(init=False)
    _definitions_base: DefinitionsBase = field(init=False)

    def __post_init__(self) -> None:
        self._language_base = MultiLanguageBaseProvider(
            primary=LanguageBaseProvider(),
            fallback=LanguageBaseProvider(
                db_path=default_fallback_language_base_path()
            ),
        )
        self._definitions_base = DefinitionsBaseProvider()

    def translate(
        self,
        text: str,
        lookup_text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]:
        cache_key = _translation_key(text, source_lang, target_lang)
        cached = self.result_cache.get(cache_key)
        if cached is not None:
            future: Future[TranslationResult] = Future()
            future.set_result(cached)
            return future
        with self._state_lock:
            inflight = self._inflight.get(cache_key)
            if inflight is not None and not inflight.done():
                return inflight
            generation = self._generation
        coro = self._translate_async(
            text,
            lookup_text,
            source_lang,
            target_lang,
            generation=generation,
            cache_key=cache_key,
            on_partial=on_partial,
        )
        future = asyncio.run_coroutine_threadsafe(coro, self.runtime.loop)
        self._register_future(cast(Future[object], future))
        self._register_inflight(cache_key, future)
        return future

    def get_cached(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult | None:
        return self.result_cache.get(_translation_key(text, source_lang, target_lang))

    def refresh_examples(
        self,
        lookup_text: str,
        *,
        limit: int,
    ) -> Future[tuple[Example, ...]]:
        future = asyncio.run_coroutine_threadsafe(
            self._refresh_examples_async(lookup_text, limit=limit),
            self.runtime.loop,
        )
        self._register_future(cast(Future[object], future))
        return future

    def warmup(self) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ensure_fetcher(), self.runtime.loop
            )
            future.add_done_callback(lambda done: done.exception())
            if _should_warmup_language_base():
                resources_future = asyncio.run_coroutine_threadsafe(
                    warmup_pipeline_resources(
                        language_base=self._language_base,
                        definitions_base=self._definitions_base,
                    ),
                    self.runtime.loop,
                )
                resources_future.add_done_callback(lambda done: done.exception())
        except Exception:
            return

    def cancel_active(self) -> None:
        with self._state_lock:
            self._generation += 1
            active = list(self._active)
            self._active.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()
        for future in active:
            future.cancel()
        for future in inflight:
            future.cancel()
        asyncio.run_coroutine_threadsafe(self._abort_session(), self.runtime.loop)

    async def _translate_async(
        self,
        text: str,
        lookup_text: str,
        source_lang: str,
        target_lang: str,
        *,
        generation: int,
        cache_key: str,
        on_partial: Callable[[TranslationResult], None] | None,
    ) -> TranslationResult:
        fetcher = await self._ensure_fetcher()
        emitted = False

        def handle_partial(result: TranslationResult) -> None:
            nonlocal emitted
            if emitted or result.status is not TranslationStatus.SUCCESS:
                return
            if not self._is_generation_active(generation):
                return
            emitted = True
            if on_partial is not None:
                on_partial(result)

        result = await translate_async(
            text,
            source_lang,
            target_lang,
            lookup_text=lookup_text,
            fetcher=fetcher,
            language_base=self._language_base,
            definitions_base=self._definitions_base,
            on_partial=handle_partial,
        )
        if not self._is_generation_active(generation):
            raise asyncio.CancelledError()
        if result.status is TranslationStatus.SUCCESS:
            self.result_cache.set(cache_key, result)
        return result

    async def _refresh_examples_async(
        self,
        lookup_text: str,
        *,
        limit: int,
    ) -> tuple[Example, ...]:
        normalized = normalize_text(lookup_text)
        if not normalized or limit <= 0 or not self._language_base.is_available:
            return ()
        loop = asyncio.get_running_loop()
        examples = await loop.run_in_executor(
            None,
            lambda: self._language_base.get_examples(word=normalized, limit=limit),
        )
        return tuple(filter_examples(list(examples)))

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
            self._fetcher = build_latency_fetcher(
                self._session,
                cache=self._http_cache,
            )
            return self._fetcher

    async def close(self) -> None:
        await self._abort_session()

    def _register_future(self, future: Future[object]) -> None:
        with self._state_lock:
            self._active.add(future)

        def _discard(done: Future[object]) -> None:
            del done
            with self._state_lock:
                self._active.discard(future)

        future.add_done_callback(_discard)

    def _register_inflight(self, key: str, future: Future[TranslationResult]) -> None:
        with self._state_lock:
            self._inflight[key] = future

        def _drop_if_current(done: Future[TranslationResult]) -> None:
            del done
            with self._state_lock:
                current = self._inflight.get(key)
                if current is future:
                    self._inflight.pop(key, None)

        future.add_done_callback(_drop_if_current)

    def _is_generation_active(self, generation: int) -> bool:
        with self._state_lock:
            return generation == self._generation

    async def _abort_session(self) -> None:
        if self._session is None:
            return
        await self._session.close()
        self._session = None
        self._fetcher = None


def _cache_key(text: str, source_lang: str, target_lang: str) -> str:
    normalized = normalize_text(text)
    return f"{source_lang}:{target_lang}:{normalized}"


def _translation_key(text: str, source_lang: str, target_lang: str) -> str:
    return _cache_key(text, source_lang, target_lang)


def _should_warmup_language_base() -> bool:
    value = os.environ.get("TRANSLATOR_WARMUP_LANGUAGE_BASE_ON_START", "1")
    normalized = value.strip().lower()
    return normalized not in {"0", "false", "no", "off"}
