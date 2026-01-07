from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from desktop_app.anki import DEFAULT_TIMEOUT_SECONDS
from desktop_app.anki.connect_config import detect_anki_connect_url
from desktop_app.application.anki_flow import AnkiFlow
from desktop_app.adapters.desktop_entry import DesktopEntryManager
from desktop_app.adapters.signal_adapter import SignalAdapter
from desktop_app.application.autostart_flow import AutostartFlow
from desktop_app.application.desktop_entry_flow import DesktopEntryFlow
from desktop_app.application.process_flow import ProcessFlow
from desktop_app.application.signal_flow import SignalFlow
from desktop_app.application.tray_flow import TrayFlow
from desktop_app.adapters.tray import TrayManager
from desktop_app.application.translation_flow import TranslationFlow
from desktop_app.anki.service import AnkiService
from desktop_app.services.history import HistoryStore
from desktop_app.services.notifier import Notifier
from desktop_app.services.result_cache import ResultCache
from desktop_app.services.runtime import AsyncRuntime
from desktop_app.services.translation_service import TranslationService


@dataclass(slots=True)
class AppServices:
    runtime: AsyncRuntime
    translator: TranslationService
    anki: AnkiService
    notifier: Notifier
    history: HistoryStore
    translation_flow: TranslationFlow
    anki_flow: AnkiFlow
    autostart_flow: AutostartFlow
    desktop_entry_flow: DesktopEntryFlow
    process_flow: ProcessFlow
    signal_flow: SignalFlow
    tray_flow: TrayFlow

    @classmethod
    def create(cls, send: Callable[[str, str], None]) -> "AppServices":
        runtime = AsyncRuntime()
        notifier = Notifier(send)
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
        autostart_flow = AutostartFlow()
        desktop_entry_flow = DesktopEntryFlow(
            manager=DesktopEntryManager(app_id="com.translator.desktop"),
        )
        process_flow = ProcessFlow(app_id="com.translator.desktop")
        signal_flow = SignalFlow(signal=SignalAdapter())
        tray_flow = TrayFlow(manager=TrayManager())
        return cls(
            runtime=runtime,
            translator=translator,
            anki=anki,
            notifier=notifier,
            history=history,
            translation_flow=translation_flow,
            anki_flow=anki_flow,
            autostart_flow=autostart_flow,
            desktop_entry_flow=desktop_entry_flow,
            process_flow=process_flow,
            signal_flow=signal_flow,
            tray_flow=tray_flow,
        )

    def start(self) -> None:
        self.runtime.start()
        self.translator.warmup()

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
