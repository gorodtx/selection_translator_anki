"""Toggling a source off must stop it being consulted, not just ignored."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from desktop_app.config import JsonValue, config_from_dict, config_to_dict
from desktop_app.infrastructure.services.result_cache import ResultCache
from translate_logic.application.pipeline import translate as pipeline
from translate_logic.infrastructure.providers import apple
from translate_logic.infrastructure.providers.cambridge import CambridgeResult
from translate_logic.infrastructure.providers.google import GoogleResult
from translate_logic.models import Example, FieldValue, SourceToggles, TranslationResult

ALL_OFF = SourceToggles(
    apple_dictionary=False,
    apple_translation=False,
    google=False,
    cambridge=False,
    offline_examples=False,
    definitions_pack=False,
)


def test_defaults_are_every_source_on() -> None:
    toggles = SourceToggles()

    assert toggles.any_network and toggles.any_apple
    assert all(
        getattr(toggles, name)
        for name in (
            "apple_dictionary",
            "apple_translation",
            "google",
            "cambridge",
            "offline_examples",
            "definitions_pack",
        )
    )


def test_a_config_written_before_toggles_existed_keeps_everything_on() -> None:
    legacy: JsonValue = {"languages": {"source": "en", "target": "ru"}}

    assert config_from_dict(legacy).sources == SourceToggles()


def test_unknown_and_partial_keys_do_not_disable_anything() -> None:
    parsed = config_from_dict({"sources": {"google": False, "made_up": True}})

    assert parsed.sources.google is False
    assert parsed.sources.cambridge is True
    assert parsed.sources.apple_dictionary is True


def test_toggles_survive_a_round_trip() -> None:
    config = replace(
        config_from_dict({}), sources=SourceToggles(google=False, cambridge=False)
    )

    assert config_from_dict(config_to_dict(config)).sources == config.sources


def test_disabled_network_providers_are_never_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_google(*args: object, **kwargs: object) -> GoogleResult:
        calls.append("google")
        return GoogleResult(translations=["из сети"], definitions_en=[])

    async def fake_cambridge(*args: object, **kwargs: object) -> CambridgeResult:
        calls.append("cambridge")
        return CambridgeResult(
            found=True, translations=["из словаря"], examples=[], definitions_en=[]
        )

    monkeypatch.setattr(pipeline, "translate_google", fake_google)
    monkeypatch.setattr(pipeline, "translate_cambridge", fake_cambridge)

    async def scenario() -> TranslationResult:
        async def fetcher(url: str) -> str:
            raise AssertionError(f"the network was touched: {url}")

        return await pipeline.translate_async(
            "bank",
            "en",
            "ru",
            lookup_text="bank",
            fetcher=fetcher,
            sources=ALL_OFF,
        )

    result = asyncio.run(scenario())

    assert calls == [], calls
    assert result.translation_ru == FieldValue.missing()


def test_enabling_only_google_leaves_cambridge_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_google(*args: object, **kwargs: object) -> GoogleResult:
        calls.append("google")
        return GoogleResult(translations=["банк"], definitions_en=[])

    async def fake_cambridge(*args: object, **kwargs: object) -> CambridgeResult:
        calls.append("cambridge")
        return CambridgeResult(
            found=True, translations=["берег"], examples=[], definitions_en=[]
        )

    monkeypatch.setattr(pipeline, "translate_google", fake_google)
    monkeypatch.setattr(pipeline, "translate_cambridge", fake_cambridge)

    async def scenario() -> TranslationResult:
        async def fetcher(url: str) -> str:
            return ""

        return await pipeline.translate_async(
            "bank",
            "en",
            "ru",
            lookup_text="bank",
            fetcher=fetcher,
            sources=replace(ALL_OFF, google=True),
        )

    result = asyncio.run(scenario())

    assert calls == ["google"], calls
    assert result.translation_ru.text == "банк"


def test_apple_lookup_asks_only_for_the_engines_that_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    class _Helper:
        async def define(self, text: str, *, timeout: float) -> None:
            del text, timeout
            asked.append("define")
            return None

        async def translate(
            self, text: str, *, source: str, target: str, timeout: float
        ) -> None:
            del text, source, target, timeout
            asked.append("translate")
            return None

    monkeypatch.setattr(apple, "get_helper", lambda: _Helper())

    async def scenario() -> None:
        await apple.lookup(
            text="bank",
            lookup_text="bank",
            source_lang="en",
            target_lang="ru",
            allow_dictionary=True,
            allow_translation=False,
        )
        assert asked == ["define"], asked
        asked.clear()
        await apple.lookup(
            text="bank",
            lookup_text="bank",
            source_lang="en",
            target_lang="ru",
            allow_dictionary=False,
            allow_translation=False,
        )
        assert asked == [], asked

    asyncio.run(scenario())


def test_changing_a_toggle_drops_cached_results() -> None:
    from desktop_app.infrastructure.services.runtime import AsyncRuntime
    from desktop_app.infrastructure.services.translation_service import (
        TranslationService,
    )

    cache = ResultCache()
    service = TranslationService(AsyncRuntime(), cache)
    cached = TranslationResult(
        translation_ru=FieldValue.present("банк"), examples=(Example("A bank."),)
    )
    cache.set("en:ru:bank", cached)
    assert service.get_cached("bank", "en", "ru") == cached

    service.update_sources(SourceToggles(google=False))

    # A result produced while Google was on must not answer a request made
    # after it was switched off.
    assert service.get_cached("bank", "en", "ru") is None
    assert service.sources.google is False


def test_updating_to_the_same_toggles_keeps_the_cache() -> None:
    from desktop_app.infrastructure.services.runtime import AsyncRuntime
    from desktop_app.infrastructure.services.translation_service import (
        TranslationService,
    )

    cache = ResultCache()
    service = TranslationService(AsyncRuntime(), cache)
    cached = TranslationResult(translation_ru=FieldValue.present("банк"))
    cache.set("en:ru:bank", cached)

    service.update_sources(SourceToggles())

    assert service.get_cached("bank", "en", "ru") == cached
