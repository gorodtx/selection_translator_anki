from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import (
    Future,
    ProcessPoolExecutor,
    TimeoutError as FutureTimeout,
)
from dataclasses import dataclass, field
from pathlib import Path

from desktop_app.services.result_cache import ResultCache
from desktop_app.services.runtime import AsyncRuntime
from desktop_app import telemetry
from translate_logic.application.translate import translate_async
from translate_logic.models import TranslationResult, TranslationStatus
from translate_logic.providers.example_generator import (
    ExampleGenerator,
    ExampleGeneratorService,
)
from translate_logic.providers.mt0_worker import generate_mt0_prompt
from translate_logic.providers.opus_mt import OpusMtProvider
from translate_logic.text import normalize_text

MODEL_DIR = Path.home() / ".local" / "share" / "translator" / "models"
MT0_MODEL_NAME = "google/mt0-small"


def _future_set() -> set[Future[TranslationResult]]:
    return set()


def _build_example_service(
    generator: Callable[[str], str],
) -> ExampleGeneratorService:
    return ExampleGeneratorService(generator=ExampleGenerator(generator=generator))


@dataclass(slots=True)
class TranslationService:
    runtime: AsyncRuntime
    result_cache: ResultCache

    mt0_timeout_seconds: float = 5.0
    mt0_max_new_tokens: int = 128
    mt0_temperature: float = 0.3

    _active: set[Future[TranslationResult]] = field(default_factory=_future_set)
    _pool: ProcessPoolExecutor | None = None
    _opus_provider: OpusMtProvider = field(init=False)
    _example_service: ExampleGeneratorService = field(init=False)

    def __post_init__(self) -> None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self._opus_provider = OpusMtProvider(model_dir=MODEL_DIR)
        self._example_service = _build_example_service(self._run_mt0_prompt)

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
            telemetry.log_event("translation.cache_hit", **telemetry.text_meta(text))
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
        return

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
            example_service=self._example_service,
            on_partial=handle_partial,
        )
        cache_key = _cache_key(text, source_lang, target_lang)
        if result.status is TranslationStatus.SUCCESS:
            self.result_cache.set(cache_key, result)
        return result

    async def close(self) -> None:
        if self._pool is None:
            return
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._pool = None

    def _register_future(self, future: Future[TranslationResult]) -> None:
        self._active.add(future)
        future.add_done_callback(self._active.discard)

    def _ensure_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1)
        return self._pool

    def _run_mt0_prompt(self, prompt: str) -> str:
        pool = self._ensure_pool()
        future = pool.submit(
            generate_mt0_prompt,
            prompt,
            MT0_MODEL_NAME,
            str(MODEL_DIR),
            self.mt0_max_new_tokens,
            self.mt0_temperature,
        )
        try:
            return future.result(timeout=self.mt0_timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise TimeoutError("mt0 generation timeout") from exc


def _cache_key(text: str, source_lang: str, target_lang: str) -> str:
    normalized = normalize_text(text)
    return f"{source_lang}:{target_lang}:{normalized}"
