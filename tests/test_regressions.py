from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
import time
from typing import Any, cast

import pytest

from desktop_app.application.history import HistoryItem
from desktop_app.application.query import QueryError, QueryOutcome, prepare_query
from desktop_app.application.use_cases.translation_executor import TranslationExecutor
from desktop_app.application.use_cases.translation_flow import TranslationFlow
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig, LanguageConfig
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


class _FakeHistory:
    def add(self, text: str, result: TranslationResult) -> None:
        del text, result

    def snapshot(self) -> list[HistoryItem]:
        return []


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
