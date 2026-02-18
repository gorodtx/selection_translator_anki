from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.infrastructure.anki import DEFAULT_TIMEOUT_SECONDS
from desktop_app.infrastructure.anki.connect_config import detect_anki_connect_url
from desktop_app.application.use_cases.anki_flow import AnkiFlow
from desktop_app.application.use_cases.translation_flow import TranslationFlow
from desktop_app.infrastructure.anki.service import AnkiService
from desktop_app.infrastructure.services.history import HistoryStore
from desktop_app.infrastructure.services.result_cache import ResultCache
from desktop_app.infrastructure.services.runtime import AsyncRuntime
from desktop_app.infrastructure.services.selection_cache import SelectionCache, selection_cache_path
from desktop_app.infrastructure.services.translation_service import TranslationService


@dataclass(slots=True)
class AppServices:
    runtime: AsyncRuntime
    translator: TranslationService
    anki: AnkiService
    history: HistoryStore
    translation_flow: TranslationFlow
    anki_flow: AnkiFlow
    selection_cache: SelectionCache

    @classmethod
    def create(cls) -> "AppServices":
        runtime = AsyncRuntime()
        result_cache = ResultCache()
        translator = TranslationService(runtime, result_cache)
        anki_url = detect_anki_connect_url() or "http://127.0.0.1:8765"
        anki = AnkiService(
            runtime,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            base_url=anki_url,
        )
        history = HistoryStore(
            max_entries=result_cache.max_entries,
        )
        translation_flow = TranslationFlow(translator=translator, history=history)
        anki_flow = AnkiFlow(service=anki)
        selection_cache = SelectionCache(selection_cache_path())
        return cls(
            runtime=runtime,
            translator=translator,
            anki=anki,
            history=history,
            translation_flow=translation_flow,
            anki_flow=anki_flow,
            selection_cache=selection_cache,
        )

    def start(self) -> None:
        self.runtime.start()
        self.translator.warmup()

    def stop(self) -> None:
        close_translator: Future[None] = asyncio.run_coroutine_threadsafe(
            self.translator.close(), self.runtime.loop
        )
        close_anki: Future[None] = asyncio.run_coroutine_threadsafe(
            self.anki.close(), self.runtime.loop
        )
        _drain_future(close_translator)
        _drain_future(close_anki)
        self.runtime.stop()

    def cancel_active(self) -> None:
        self.translator.cancel_active()
        self.anki.cancel_active()


def _drain_future(future: Future[None]) -> None:
    try:
        if future.done():
            future.result()
            return
        future.cancel()
    except Exception:
        pass
