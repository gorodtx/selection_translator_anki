from __future__ import annotations

import asyncio
import time

import aiohttp
import pytest

from translate_logic.application.translate import (
    _recover_empty_translation_async,
    _translate_with_fetcher_async,
)
from translate_logic.http import FailureBackoffStore, FetchError, build_async_fetcher
from translate_logic.providers.cambridge import CambridgeResult
from translate_logic.providers.google import GoogleResult


def test_fetcher_uses_host_specific_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[float] = []

    async def fake_fetch_text_async(
        url: str,
        session: object,
        timeout: float,
    ) -> str:
        observed.append(timeout)
        return url

    monkeypatch.setattr("translate_logic.http.fetch_text_async", fake_fetch_text_async)

    async def run() -> None:
        async with aiohttp.ClientSession() as session:
            fetcher = build_async_fetcher(
                session=session,
                timeout=9.0,
                timeouts_by_host={"api.example.com": 1.25},
                failure_backoff_seconds=0,
            )
            await fetcher("https://api.example.com/ping")
            await fetcher("https://other.example.com/ping")

    asyncio.run(run())

    assert observed == [1.25, 9.0]


def test_fetcher_pattern_timeout_overrides_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[float] = []

    async def fake_fetch_text_async(
        url: str,
        session: object,
        timeout: float,
    ) -> str:
        observed.append(timeout)
        return url

    monkeypatch.setattr("translate_logic.http.fetch_text_async", fake_fetch_text_async)

    async def run() -> None:
        async with aiohttp.ClientSession() as session:
            fetcher = build_async_fetcher(
                session=session,
                timeout=9.0,
                timeouts_by_host={"dictionary.cambridge.org": 2.5},
                timeouts_by_pattern=(("datasetsearch=english-russian", 1.8),),
                failure_backoff_seconds=0,
            )
            await fetcher(
                "https://dictionary.cambridge.org/search/direct/?datasetsearch=english-russian&q=hello"
            )

    asyncio.run(run())

    assert observed == [1.8]


def test_fetcher_failure_backoff_skips_immediate_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    now = 0.0

    def fake_monotonic() -> float:
        return now

    async def flaky_fetch_text_async(
        url: str,
        session: object,
        timeout: float,
    ) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FetchError("temporary failure")
        return "ok"

    monkeypatch.setattr("translate_logic.http.time.monotonic", fake_monotonic)
    monkeypatch.setattr("translate_logic.http.fetch_text_async", flaky_fetch_text_async)

    async def run() -> None:
        nonlocal now
        async with aiohttp.ClientSession() as session:
            fetcher = build_async_fetcher(
                session=session,
                failure_backoff_seconds=5.0,
            )
            with pytest.raises(FetchError):
                await fetcher("https://api.example.com/fail")
            now = 1.0
            with pytest.raises(FetchError):
                await fetcher("https://api.example.com/fail")
            now = 6.0
            payload = await fetcher("https://api.example.com/fail")
            assert payload == "ok"

    asyncio.run(run())

    assert attempts == 2


def test_shared_failure_backoff_store_applies_across_fetchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    now = 0.0
    shared_store = FailureBackoffStore(ttl_seconds=5.0, max_entries=16)

    def fake_monotonic() -> float:
        return now

    async def always_fail(
        url: str,
        session: object,
        timeout: float,
    ) -> str:
        nonlocal attempts
        attempts += 1
        raise FetchError("failure")

    monkeypatch.setattr("translate_logic.http.time.monotonic", fake_monotonic)
    monkeypatch.setattr("translate_logic.http.fetch_text_async", always_fail)

    async def run() -> None:
        async with (
            aiohttp.ClientSession() as session_a,
            aiohttp.ClientSession() as session_b,
        ):
            fetcher_a = build_async_fetcher(
                session=session_a,
                failure_backoff_store=shared_store,
                failure_backoff_seconds=0,
            )
            fetcher_b = build_async_fetcher(
                session=session_b,
                failure_backoff_store=shared_store,
                failure_backoff_seconds=0,
            )
            with pytest.raises(FetchError):
                await fetcher_a("https://api.example.com/fail")
            with pytest.raises(FetchError):
                await fetcher_b("https://api.example.com/fail")

    asyncio.run(run())

    assert attempts == 1


def test_cambridge_flow_prefetches_google_for_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cambridge_finished = False
    google_started_before_cambridge_done = False

    async def fake_cambridge(_text: str, _fetcher: object) -> CambridgeResult:
        nonlocal cambridge_finished
        await asyncio.sleep(0.05)
        cambridge_finished = True
        return CambridgeResult(
            found=False,
            translations=[],
            examples=[],
        )

    async def fake_google(
        _text: str,
        _source_lang: str,
        _target_lang: str,
        _fetcher: object,
    ) -> GoogleResult:
        nonlocal google_started_before_cambridge_done
        google_started_before_cambridge_done = not cambridge_finished
        return GoogleResult(translations=["перевод"])

    async def fake_fetcher(url: str) -> str:
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(
        "translate_logic.application.translate._run_cambridge_with_budget",
        fake_cambridge,
    )
    monkeypatch.setattr(
        "translate_logic.application.translate._run_google_with_budget", fake_google
    )

    async def run() -> None:
        result = await _translate_with_fetcher_async(
            text="hello",
            source_lang="en",
            target_lang="ru",
            fetcher=fake_fetcher,
            language_base=None,
            on_partial=None,
        )
        assert result.translation_ru.text == "перевод"

    asyncio.run(run())

    assert google_started_before_cambridge_done is True


def test_single_char_prefers_google_without_waiting_cambridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cambridge_completed = False

    async def slow_cambridge(_text: str, _fetcher: object) -> CambridgeResult:
        nonlocal cambridge_completed
        await asyncio.sleep(0.2)
        cambridge_completed = True
        return CambridgeResult(
            found=True,
            translations=["кембридж"],
            examples=[],
        )

    async def fast_google(
        _text: str,
        _source_lang: str,
        _target_lang: str,
        _fetcher: object,
    ) -> GoogleResult:
        await asyncio.sleep(0.01)
        return GoogleResult(translations=["гугл"])

    async def fake_fetcher(url: str) -> str:
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(
        "translate_logic.application.translate._run_cambridge_with_budget",
        slow_cambridge,
    )
    monkeypatch.setattr(
        "translate_logic.application.translate._run_google_with_budget",
        fast_google,
    )

    async def run() -> tuple[float, str]:
        started = time.perf_counter()
        result = await _translate_with_fetcher_async(
            text="a",
            source_lang="en",
            target_lang="ru",
            fetcher=fake_fetcher,
            language_base=None,
            on_partial=None,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return elapsed_ms, result.translation_ru.text

    elapsed_ms, translation = asyncio.run(run())

    assert translation == "гугл"
    assert elapsed_ms < 180.0
    assert cambridge_completed is False


def test_recover_empty_translation_uses_relaxed_google(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fast_google(
        _text: str,
        _source_lang: str,
        _target_lang: str,
        _fetcher: object,
    ) -> GoogleResult:
        await asyncio.sleep(0.01)
        return GoogleResult(translations=["восстановлено"])

    async def fake_fetcher(url: str) -> str:
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(
        "translate_logic.application.translate.translate_google", fast_google
    )

    async def run() -> str | None:
        return await _recover_empty_translation_async(
            text="run",
            source_lang="en",
            target_lang="ru",
            fetcher=fake_fetcher,
            current_translation=None,
            secondary_translations=None,
        )

    recovered = asyncio.run(run())
    assert recovered == "восстановлено"
