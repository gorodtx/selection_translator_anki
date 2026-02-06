from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field

from desktop_app.services.result_cache import ResultCache
from desktop_app.services.runtime import AsyncRuntime
from translate_logic.application.translate import translate_async
from translate_logic.language_base.multi_provider import MultiLanguageBaseProvider
from translate_logic.language_base.provider import (
    LanguageBaseProvider,
    default_fallback_language_base_path,
)
from translate_logic.language_base.base import LanguageBase
from translate_logic.models import TranslationResult, TranslationStatus
from translate_logic.providers.opus_mt import OpusMtProvider, default_opus_mt_model_dir
from translate_logic.text import normalize_text

MODEL_DIR = default_opus_mt_model_dir()


def _future_set() -> set[Future[TranslationResult]]:
    return set()


@dataclass(slots=True)
class TranslationService:
    runtime: AsyncRuntime
    result_cache: ResultCache

    _active: set[Future[TranslationResult]] = field(default_factory=_future_set)
    _warmup_future: Future[None] | None = field(default=None, init=False)
    _opus_provider: OpusMtProvider = field(init=False)
    _language_base: LanguageBase = field(init=False)

    def __post_init__(self) -> None:
        self._opus_provider = OpusMtProvider(model_dir=MODEL_DIR)
        self._language_base = MultiLanguageBaseProvider(
            primary=LanguageBaseProvider(),
            fallback=LanguageBaseProvider(
                db_path=default_fallback_language_base_path()
            ),
        )

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

    def cached(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult | None:
        cache_key = _cache_key(text, source_lang, target_lang)
        return self.result_cache.get(cache_key)

    def warmup(self) -> None:
        if self._warmup_future is not None:
            return

        async def _warmup() -> None:
            # Best-effort: if offline assets are missing, provider.warmup()
            # becomes a no-op.
            self._opus_provider.warmup()

        try:
            self._warmup_future = asyncio.run_coroutine_threadsafe(
                _warmup(), self.runtime.loop
            )
        except RuntimeError:
            # Runtime is not started.
            self._warmup_future = None

    def cancel_active(self) -> None:
        for future in list(self._active):
            future.cancel()
        self._active.clear()

    async def _translate_async(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None,
    ) -> TranslationResult:
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
            opus_provider=self._opus_provider,
            language_base=self._language_base,
            on_partial=handle_partial,
        )
        cache_key = _cache_key(text, source_lang, target_lang)
        if result.status is TranslationStatus.SUCCESS:
            self.result_cache.set(cache_key, result)
        return result

    async def close(self) -> None:
        return

    def _register_future(self, future: Future[TranslationResult]) -> None:
        self._active.add(future)
        future.add_done_callback(self._active.discard)


def _cache_key(text: str, source_lang: str, target_lang: str) -> str:
    normalized = normalize_text(text)
    return f"{source_lang}:{target_lang}:{normalized}"
