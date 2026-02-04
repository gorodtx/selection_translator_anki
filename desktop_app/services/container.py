from __future__ import annotations

import asyncio
from dataclasses import dataclass

from desktop_app.anki import DEFAULT_TIMEOUT_SECONDS
from desktop_app.anki.connect_config import detect_anki_connect_url
from desktop_app.application.anki_flow import AnkiFlow
from desktop_app.application.translation_flow import TranslationFlow
from desktop_app.anki.service import AnkiService
from desktop_app.services.history import HistoryStore
from desktop_app.services.result_cache import ResultCache
from desktop_app.services.runtime import AsyncRuntime
from desktop_app.services.translation_service import TranslationService


@dataclass(slots=True)
class AppServices:
    runtime: AsyncRuntime
    translator: TranslationService
    anki: AnkiService
    history: HistoryStore
    translation_flow: TranslationFlow
    anki_flow: AnkiFlow

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
            ttl_seconds=result_cache.ttl_seconds,
        )
        translation_flow = TranslationFlow(translator=translator, history=history)
        anki_flow = AnkiFlow(service=anki)
        return cls(
            runtime=runtime,
            translator=translator,
            anki=anki,
            history=history,
            translation_flow=translation_flow,
            anki_flow=anki_flow,
        )

    def start(self) -> None:
        self.runtime.start()

    def stop(self) -> None:
        close_translator = asyncio.run_coroutine_threadsafe(
            self.translator.close(), self.runtime.loop
        )
        close_anki = asyncio.run_coroutine_threadsafe(
            self.anki.close(), self.runtime.loop
        )
        for future in [close_translator, close_anki]:
            try:
                future.result(timeout=1.0)
            except Exception:
                continue
        self.runtime.stop()

    def cancel_active(self) -> None:
        self.translator.cancel_active()
        self.anki.cancel_active()
