from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
import time
from typing import Any, cast

import pytest

from desktop_app.application.examples_state import EntryExamplesState
from desktop_app.application.history import HistoryItem
from desktop_app.application.query import QueryError, QueryOutcome, prepare_query
from desktop_app.application.use_cases.translation_executor import TranslationExecutor
from desktop_app.application.use_cases.translation_flow import TranslationFlow
from desktop_app.application.use_cases.translation_executor import PreparedTranslation
from desktop_app.application.view_state import TranslationPresenter
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig, LanguageConfig
from desktop_app.presentation.controllers import translation_controller as controller_module
from translate_logic.application.pipeline import translate as pipeline
from translate_logic.infrastructure.http.transport import (
    FetchStatusError,
    fetch_text_async,
    normalize_url_cache_key,
)
from translate_logic.infrastructure.language_base.multi_provider import (
    MultiLanguageBaseProvider,
)
from translate_logic.infrastructure.providers.cambridge import CambridgeResult
from translate_logic.infrastructure.providers.google import GoogleResult
from translate_logic.models import Example, FieldValue, TranslationResult


def test_prepare_query_preserves_network_text_and_normalizes_lookup_text() -> None:
    outcome = prepare_query("  time, to make up?  ", "en", "ru")

    assert outcome == QueryOutcome(
        display_text="time, to make up?",
        network_text="time, to make up?",
        lookup_text="time to make up",
        error=None,
    )


def test_prepare_query_rejects_non_english_noise() -> None:
    outcome = prepare_query(" --- '' ", "en", "ru")

    assert outcome.error is QueryError.NO_ENGLISH
    assert outcome.network_text is None
    assert outcome.lookup_text is None


def test_multi_language_base_provider_tops_up_from_fallback() -> None:
    primary = _FakeLanguageBase(
        [Example("Primary example sentence."), Example("Shared example sentence.")]
    )
    fallback = _FakeLanguageBase(
        [Example("Shared example sentence."), Example("Fallback example sentence.")]
    )
    provider = MultiLanguageBaseProvider(primary=primary, fallback=fallback)

    examples = provider.get_examples(word="time", limit=3)

    assert examples == (
        Example("Primary example sentence."),
        Example("Shared example sentence."),
        Example("Fallback example sentence."),
    )


def test_prepare_uses_cached_network_text() -> None:
    cached = TranslationResult(
        translation_ru=FieldValue.present("время"),
        definitions_en=("definition",),
        examples=(Example("Time moves quickly."),),
    )
    translator = _FakeTranslator(cached)
    flow = TranslationFlow(
        translator=translator,
        history=_FakeHistory(),
    )
    executor = TranslationExecutor(flow=flow, config=_app_config())

    prepared = executor.prepare("time, now")

    assert prepared is not None
    assert prepared.display_text == "time, now"
    assert prepared.network_text == "time, now"
    assert prepared.lookup_text == "time now"
    assert prepared.cached is cached
    assert translator.cached_requests == [("time, now", "en", "ru")]


def test_fetch_text_async_raises_for_http_errors() -> None:
    session = _FakeSession(status=503, payload="backend unavailable")

    with pytest.raises(FetchStatusError) as exc_info:
        asyncio.run(
            fetch_text_async(
                "https://example.com/fail",
                cast(Any, session),
            )
        )

    assert exc_info.value.status_code == 503


def test_normalize_url_cache_key_ignores_google_attempt_only() -> None:
    google_one = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=en&tl=ru&q=time&attempt=1"
    )
    google_two = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=en&tl=ru&q=time&attempt=2"
    )
    other_one = "https://example.com/api?q=time&attempt=1"
    other_two = "https://example.com/api?q=time&attempt=2"

    assert normalize_url_cache_key(google_one) == normalize_url_cache_key(google_two)
    assert normalize_url_cache_key(other_one) != normalize_url_cache_key(other_two)


def test_translate_async_emits_partial_before_slow_offline_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial_times: list[float] = []
    language_base = _SlowLanguageBase(
        [Example("This is a slow example sentence.")]
    )
    definitions_base = _SlowDefinitionsBase(["slow definition"])

    async def fake_google(
        text: str,
        source_lang: str,
        target_lang: str,
        fetcher: Any,
    ) -> GoogleResult:
        del text, source_lang, target_lang, fetcher
        return GoogleResult(translations=["время"], definitions_en=[])

    async def fake_cambridge(text: str, fetcher: Any) -> CambridgeResult:
        del text, fetcher
        return CambridgeResult(
            found=False,
            translations=[],
            examples=[],
            definitions_en=[],
        )

    monkeypatch.setattr(pipeline, "_run_google_with_budget", fake_google)
    monkeypatch.setattr(pipeline, "_run_cambridge_with_budget", fake_cambridge)

    start = time.perf_counter()

    result = asyncio.run(
        pipeline.translate_async(
            "time, now",
            source_lang="en",
            target_lang="ru",
            lookup_text="time now",
            fetcher=_unused_fetcher,
            language_base=language_base,
            definitions_base=definitions_base,
            on_partial=lambda partial: partial_times.append(time.perf_counter()),
        )
    )

    total_elapsed = time.perf_counter() - start

    assert partial_times, "expected an early partial result"
    first_partial_elapsed = partial_times[0] - start
    assert first_partial_elapsed < 0.12
    assert total_elapsed - first_partial_elapsed > 0.20
    assert result.translation_ru.text == "время"
    assert result.definitions_en == ("slow definition",)
    assert result.examples == (Example("This is a slow example sentence."),)


def test_translate_async_waits_for_cambridge_when_google_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_google(
        text: str,
        source_lang: str,
        target_lang: str,
        fetcher: Any,
    ) -> GoogleResult:
        del text, source_lang, target_lang, fetcher
        return GoogleResult(translations=[], definitions_en=[])

    async def fake_cambridge(text: str, fetcher: Any) -> CambridgeResult:
        del fetcher
        await asyncio.sleep(0.35)
        return CambridgeResult(
            found=True,
            translations=[f"{text}-ru"],
            examples=[Example(f"{text} example.")],
            definitions_en=[f"{text} definition"],
        )

    monkeypatch.setattr(pipeline, "_run_google_with_budget", fake_google)
    monkeypatch.setattr(pipeline, "_run_cambridge_with_budget", fake_cambridge)

    result = asyncio.run(
        pipeline.translate_async(
            "hello",
            source_lang="en",
            target_lang="ru",
            lookup_text="hello",
            fetcher=_unused_fetcher,
            language_base=None,
            definitions_base=None,
        )
    )

    assert result.translation_ru.text == "hello-ru"
    assert result.definitions_en == ("hello definition",)
    assert result.examples == (Example("hello example."),)


def test_partial_result_preserves_lookup_text_for_examples_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_view: _FakeViewCoordinator | None = None

    def build_fake_view(**kwargs: Any) -> _FakeViewCoordinator:
        del kwargs
        nonlocal fake_view
        fake_view = _FakeViewCoordinator()
        return fake_view

    def build_fake_history(**kwargs: Any) -> _FakeHistoryCoordinator:
        del kwargs
        return _FakeHistoryCoordinator()

    monkeypatch.setattr(
        controller_module,
        "TranslationViewCoordinator",
        build_fake_view,
    )
    monkeypatch.setattr(
        controller_module,
        "HistoryViewCoordinator",
        build_fake_history,
    )

    executor = _ControllerExecutor()
    controller = controller_module.TranslationController(
        app=cast(Any, object()),
        translation_executor=cast(Any, executor),
        cancel_active=lambda: None,
        config=_app_config(),
        clipboard_writer=cast(Any, _FakeClipboardWriter()),
        anki_controller=cast(Any, _FakeAnkiController()),
        on_present_window=lambda window: None,
        on_open_settings=lambda: None,
    )
    assert fake_view is not None

    request_id = controller._state.request.next_id()
    controller._state.memory.update("hello", None, lookup_text="hello")
    fake_view.begin("hello")
    result = TranslationResult(
        translation_ru=FieldValue.present("привет"),
        definitions_en=("hello definition",),
        examples=(Example("hello example."),),
    )

    assert controller._apply_partial_result(request_id, result) is False
    assert controller._state.memory.lookup_text == "hello"

    assert controller._apply_translation_result(request_id, result) is False
    assert executor.registered_lookup_text == "hello"
    assert controller._state.memory.lookup_text == "hello"
    assert fake_view.state.can_refresh_examples is True


@dataclass
class _FakeLanguageBase:
    examples: list[Example]
    is_available: bool = True

    def get_examples(self, *, word: str, limit: int) -> tuple[Example, ...]:
        del word
        return tuple(self.examples[:limit])

    def warmup(self) -> None:
        return


@dataclass
class _SlowLanguageBase:
    examples: list[Example]
    is_available: bool = True

    def get_examples(self, *, word: str, limit: int) -> tuple[Example, ...]:
        del word
        time.sleep(0.16)
        return tuple(self.examples[:limit])

    def warmup(self) -> None:
        return


@dataclass
class _SlowDefinitionsBase:
    definitions: list[str]
    is_available: bool = True

    def get_definitions(self, *, word: str, limit: int) -> tuple[str, ...]:
        del word
        time.sleep(0.16)
        return tuple(self.definitions[:limit])

    def warmup(self) -> None:
        return


class _FakeTranslator:
    def __init__(self, cached: TranslationResult) -> None:
        self._cached = cached
        self.cached_requests: list[tuple[str, str, str]] = []

    def get_cached(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult | None:
        self.cached_requests.append((text, source_lang, target_lang))
        return self._cached

    def translate(
        self,
        text: str,
        lookup_text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Any = None,
    ) -> Future[TranslationResult]:
        del text, lookup_text, source_lang, target_lang, on_partial
        raise AssertionError("translate should not be called for cached prepare")

    def refresh_examples(
        self,
        lookup_text: str,
        *,
        limit: int,
    ) -> Future[tuple[Example, ...]]:
        del lookup_text, limit
        raise AssertionError("refresh_examples should not be called in this test")


class _FakeHistory:
    def add(self, text: str, lookup_text: str, result: TranslationResult) -> HistoryItem:
        del text, lookup_text, result
        raise AssertionError("history.add should not be called in this test")

    def get(self, entry_id: int) -> HistoryItem | None:
        del entry_id
        return None

    def find_by_text(self, text: str) -> HistoryItem | None:
        del text
        return None

    def update_examples(self, entry_id: int, examples_state: Any) -> HistoryItem | None:
        del entry_id, examples_state
        return None

    def snapshot(self) -> list[HistoryItem]:
        return []


class _FakeViewCoordinator:
    def __init__(self) -> None:
        self._presenter = TranslationPresenter()
        self._visible = False

    @property
    def state(self):  # type: ignore[override]
        return self._presenter.state

    def begin(self, original: str) -> None:
        self._presenter.begin(original)

    def apply_partial(self, result: TranslationResult) -> None:
        self._presenter.apply_partial(result)

    def apply_final(
        self,
        result: TranslationResult,
        *,
        visible_examples: tuple[Example, ...] | None = None,
        can_refresh_examples: bool = False,
        refreshing_examples: bool = False,
    ) -> None:
        self._presenter.apply_final(
            result,
            visible_examples=visible_examples,
            can_refresh_examples=can_refresh_examples,
            refreshing_examples=refreshing_examples,
        )

    def update_examples(
        self,
        *,
        examples: tuple[Example, ...],
        can_refresh_examples: bool,
        refreshing_examples: bool = False,
    ) -> None:
        self._presenter.update_examples(
            examples=examples,
            can_refresh_examples=can_refresh_examples,
            refreshing_examples=refreshing_examples,
        )

    def set_examples_refreshing(
        self,
        *,
        refreshing_examples: bool,
        can_refresh_examples: bool,
    ) -> None:
        self._presenter.set_examples_refreshing(
            refreshing_examples=refreshing_examples,
            can_refresh_examples=can_refresh_examples,
        )

    def mark_error(self) -> None:
        self._presenter.mark_error()

    def set_anki_available(self, available: bool) -> None:
        self._presenter.set_anki_available(available)

    def reset_original(self, original: str) -> None:
        self._presenter.reset_original(original)

    def present(self, *, should_present: bool) -> bool:
        self._visible = self._visible or should_present
        return should_present

    def hide(self) -> None:
        self._visible = False

    def is_visible(self) -> bool:
        return self._visible

    def window(self):
        return None

    def notify(self, notification: Any) -> None:
        del notification

    def clear_banner(self) -> None:
        return None

    def show_banner(self, notification: Any) -> None:
        del notification

    def show_anki_upsert(self, **kwargs: Any) -> None:
        del kwargs

    def hide_anki_upsert(self) -> None:
        return None


class _FakeHistoryCoordinator:
    is_open = False

    def show(self) -> None:
        return None

    def refresh(self) -> None:
        return None


class _ControllerExecutor:
    def __init__(self) -> None:
        self.registered_lookup_text: str | None = None

    def update_config(self, config: AppConfig) -> None:
        del config

    def history_snapshot(self) -> list[HistoryItem]:
        return []

    def prepare(self, text: str) -> PreparedTranslation | None:
        return PreparedTranslation(
            display_text=text,
            network_text=text,
            lookup_text=text,
            cached=None,
        )

    def register_result(
        self,
        display_text: str,
        lookup_text: str,
        result: TranslationResult,
    ) -> HistoryItem:
        del display_text
        self.registered_lookup_text = lookup_text
        return HistoryItem(
            entry_id=1,
            text="hello",
            lookup_text=lookup_text,
            result=result,
            examples_state=EntryExamplesState.from_result(
                lookup_text=lookup_text,
                result=result,
            ),
        )

    def refresh_examples(
        self,
        lookup_text: str,
        *,
        limit: int,
    ) -> Future[tuple[Example, ...]]:
        del lookup_text, limit
        future: Future[tuple[Example, ...]] = Future()
        future.set_result(())
        return future

    def update_entry_examples(
        self,
        entry_id: int,
        examples_state: EntryExamplesState,
    ) -> HistoryItem | None:
        del entry_id, examples_state
        return None

    def run(
        self,
        display_text: str,
        network_text: str,
        lookup_text: str,
        *,
        on_start: Any,
        on_partial: Any,
        on_complete: Any,
        on_error: Any,
    ) -> Future[TranslationResult]:
        del display_text, network_text, lookup_text, on_start, on_partial, on_complete, on_error
        raise AssertionError("run should not be called in this test")


class _FakeClipboardWriter:
    def copy_text(self, text: str) -> None:
        del text


class _FakeAnkiController:
    def cancel_pending(self) -> None:
        return None

    def is_config_ready(self, config: Any) -> bool:
        del config
        return True

    def prepare_upsert(self, **kwargs: Any) -> None:
        del kwargs

    def apply_upsert(self, **kwargs: Any) -> None:
        del kwargs


class _FakeResponse:
    def __init__(self, status: int, payload: str) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        del exc_type, exc, tb
        return False

    async def text(self, *, errors: str = "replace") -> str:
        del errors
        return self._payload


class _FakeSession:
    def __init__(self, *, status: int, payload: str) -> None:
        self._response = _FakeResponse(status=status, payload=payload)

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        del url, kwargs
        return self._response


def _app_config() -> AppConfig:
    return AppConfig(
        languages=LanguageConfig(source="en", target="ru"),
        anki=AnkiConfig(
            deck="",
            model="",
            fields=AnkiFieldMap(
                word="word",
                translation="translation",
                example_en="example_en",
            ),
        ),
    )


async def _unused_fetcher(url: str) -> str:
    del url
    raise AssertionError("network fetcher should not be called in this test")
