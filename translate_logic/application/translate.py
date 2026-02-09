from __future__ import annotations

import asyncio
from typing import Callable

import aiohttp

from translate_logic.cache import LruTtlCache
from translate_logic.domain import rules
from translate_logic.domain.policies import SourcePolicy
from translate_logic.http import AsyncFetcher, build_async_fetcher
from translate_logic.language_base.base import LanguageBase
from translate_logic.models import (
    Example,
    FieldValue,
    TranslationLimit,
    TranslationResult,
)
from translate_logic.providers.cambridge import CambridgeResult, translate_cambridge
from translate_logic.providers.dictionary_api import (
    DictionaryApiResult,
    translate_dictionary_api,
)
from translate_logic.providers.google import GoogleResult, translate_google
from translate_logic.providers.tatoeba import TatoebaResult, translate_tatoeba
from translate_logic.text import count_words, normalize_text
from translate_logic.translation import (
    combine_translation_variants,
    limit_translations,
    merge_translations,
    partition_translations,
    select_primary_translation,
    select_translation_candidates,
)

DEFAULT_CACHE = LruTtlCache()
_POLICY = SourcePolicy()
_LANGUAGE_BASE_EXAMPLE_LIMIT = 3


async def translate_async(
    text: str,
    source_lang: str = "en",
    target_lang: str = "ru",
    fetcher: AsyncFetcher | None = None,
    language_base: LanguageBase | None = None,
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    if fetcher is not None:
        return await _translate_with_fetcher_async(
            text, source_lang, target_lang, fetcher, language_base, on_partial
        )
    async with aiohttp.ClientSession() as session:
        async_fetcher = build_async_fetcher(session, cache=DEFAULT_CACHE)
        return await _translate_with_fetcher_async(
            text,
            source_lang,
            target_lang,
            async_fetcher,
            language_base,
            on_partial,
        )


async def _translate_with_fetcher_async(
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    language_base: LanguageBase | None = None,
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return TranslationResult.empty()
    language_base_examples = await _language_base_examples_async(
        text=normalized_text,
        language_base=language_base,
    )

    word_count = count_words(normalized_text)
    if not _POLICY.use_cambridge(word_count):
        cambridge_result = CambridgeResult(
            found=False,
            translations=[],
            ipa_uk=None,
            examples=[],
        )
        translation_ru, ipa_uk, example = await _translate_with_google_fallback_async(
            normalized_text,
            cambridge_result,
            source_lang,
            target_lang,
            fetcher,
            language_base_examples,
            on_partial,
        )
        return _build_result(
            translation_ru,
            ipa_uk,
            example,
            language_base_examples=language_base_examples,
        )

    cambridge_result = await translate_cambridge(normalized_text, fetcher)
    if cambridge_result.found:
        cambridge_non_meta, cambridge_meta = partition_translations(
            cambridge_result.translations
        )
        if cambridge_non_meta:
            translation_ru = combine_translation_variants(cambridge_non_meta, [])
            _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
            google_task: asyncio.Task[GoogleResult] | None = None
            if _needs_more_variants(cambridge_non_meta):
                google_task = asyncio.create_task(
                    translate_google(normalized_text, source_lang, target_lang, fetcher)
                )
            ipa_task = asyncio.create_task(
                _supplement_pronunciation_and_examples_async(
                    normalized_text,
                    cambridge_result.ipa_uk,
                    cambridge_result.examples,
                    source_lang,
                    target_lang,
                    fetcher,
                )
            )
            if google_task is not None:
                try:
                    google_result: GoogleResult | None = await google_task
                except Exception:
                    google_result = None
                if google_result is not None:
                    google_candidates = select_translation_candidates(
                        google_result.translations
                    )
                    if google_candidates:
                        translation_ru = combine_translation_variants(
                            cambridge_non_meta, google_candidates
                        )
            ipa_uk, example = await ipa_task
            return _build_result(
                translation_ru,
                ipa_uk,
                example,
                language_base_examples=language_base_examples,
            )
        translation_ru, ipa_uk, example = await _translate_with_google_fallback_async(
            normalized_text,
            cambridge_result,
            source_lang,
            target_lang,
            fetcher,
            language_base_examples,
            on_partial,
            secondary_translations=cambridge_meta,
        )
        return _build_result(
            translation_ru,
            ipa_uk,
            example,
            language_base_examples=language_base_examples,
        )

    translation_ru, ipa_uk, example = await _translate_with_google_fallback_async(
        normalized_text,
        cambridge_result,
        source_lang,
        target_lang,
        fetcher,
        language_base_examples,
        on_partial,
    )
    return _build_result(
        translation_ru,
        ipa_uk,
        example,
        language_base_examples=language_base_examples,
    )


async def _translate_with_google_fallback_async(
    text: str,
    cambridge_result: CambridgeResult,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    language_base_examples: list[Example],
    on_partial: Callable[[TranslationResult], None] | None = None,
    secondary_translations: list[str] | None = None,
) -> tuple[str | None, str | None, Example | None]:
    base_ipa = cambridge_result.ipa_uk if cambridge_result.found else None
    base_examples = (
        filter_examples(cambridge_result.examples) if cambridge_result.found else []
    )
    google_task: asyncio.Task[GoogleResult] = asyncio.create_task(
        translate_google(text, source_lang, target_lang, fetcher)
    )
    needs_dictionary = _POLICY.needs_dictionary(base_ipa, base_examples)
    needs_tatoeba = _POLICY.needs_tatoeba(base_examples)
    dictionary_task: asyncio.Task[DictionaryApiResult] | None = None
    tatoeba_task: asyncio.Task[TatoebaResult] | None = None
    if needs_dictionary:
        dictionary_task = asyncio.create_task(translate_dictionary_api(text, fetcher))
    if needs_tatoeba:
        tatoeba_task = asyncio.create_task(translate_tatoeba(text, fetcher))

    try:
        google_result: GoogleResult | None = await google_task
    except Exception:
        google_result = None
    google_candidates = (
        select_translation_candidates(google_result.translations)
        if google_result is not None
        else []
    )
    translation_ru = combine_translation_variants(
        google_candidates, secondary_translations or []
    )
    _emit_partial(on_partial, FieldValue.from_optional(translation_ru))

    dictionary_result = await dictionary_task if dictionary_task is not None else None
    tatoeba_result = await tatoeba_task if tatoeba_task is not None else None
    ipa_uk, example = await _supplement_pronunciation_and_examples_async(
        text,
        base_ipa,
        base_examples,
        source_lang,
        target_lang,
        fetcher,
        dictionary_result,
        tatoeba_result,
        language_base_examples,
    )
    return translation_ru, ipa_uk, example


async def _supplement_pronunciation_and_examples_async(
    text: str,
    ipa_uk: str | None,
    examples: list[Example],
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    dictionary_result: DictionaryApiResult | None = None,
    tatoeba_result: TatoebaResult | None = None,
    language_base_examples: list[Example] | None = None,
) -> tuple[str | None, Example | None]:
    available_examples = filter_examples(examples)
    local_examples = filter_examples(language_base_examples or [])
    needs_dictionary = _POLICY.needs_dictionary(ipa_uk, available_examples)
    needs_tatoeba = _POLICY.needs_tatoeba(available_examples)

    dictionary_task: asyncio.Task[DictionaryApiResult] | None = None
    tatoeba_task: asyncio.Task[TatoebaResult] | None = None
    if dictionary_result is None and needs_dictionary:
        dictionary_task = asyncio.create_task(translate_dictionary_api(text, fetcher))
    if tatoeba_result is None and needs_tatoeba:
        tatoeba_task = asyncio.create_task(translate_tatoeba(text, fetcher))

    if dictionary_task is not None:
        dictionary_result = await dictionary_task
    if dictionary_result is not None:
        if not available_examples:
            available_examples = filter_examples(dictionary_result.examples)

    if tatoeba_task is not None:
        tatoeba_result = await tatoeba_task

    paired_local_example = _select_example_with_ru(local_examples)
    if paired_local_example is not None:
        return ipa_uk, paired_local_example

    paired_example = _select_example_with_ru(available_examples)
    if paired_example is None and tatoeba_result is not None:
        paired_example = _select_example_with_ru(
            filter_examples(tatoeba_result.examples)
        )

    fallback_example = _select_any_example(available_examples)
    if fallback_example is None:
        fallback_example = _select_any_example(local_examples)
    final_example = paired_example or fallback_example
    if final_example is None:
        return ipa_uk, None

    if final_example.ru is None:
        translated = await translate_google(
            final_example.en, source_lang, target_lang, fetcher
        )
        translation_ru = select_primary_translation(translated.translations)
        if translation_ru:
            final_example = Example(en=final_example.en, ru=translation_ru)

    return ipa_uk, final_example


def _emit_partial(
    on_partial: Callable[[TranslationResult], None] | None,
    translation_ru: FieldValue,
) -> None:
    if on_partial is None or not translation_ru.is_present:
        return
    on_partial(
        TranslationResult(
            translation_ru=translation_ru,
            ipa_uk=FieldValue.missing(),
            example_en=FieldValue.missing(),
            example_ru=FieldValue.missing(),
        )
    )


def _select_example_with_ru(examples: list[Example]) -> Example | None:
    for example in examples:
        if example.ru:
            return example
    return None


def _select_any_example(examples: list[Example]) -> Example | None:
    if examples:
        return examples[0]
    return None


def _needs_more_variants(translations: list[str]) -> bool:
    unique = merge_translations(translations, [])
    limited = limit_translations(unique, TranslationLimit.PRIMARY.value)
    return len(limited) < TranslationLimit.PRIMARY.value


def _build_result(
    translation_ru: str | None,
    ipa_uk: str | None,
    example: Example | None,
    *,
    language_base_examples: list[Example],
) -> TranslationResult:
    preferred_example = _pick_preferred_example(example, language_base_examples)
    return TranslationResult(
        translation_ru=FieldValue.from_optional(translation_ru),
        ipa_uk=FieldValue.from_optional(ipa_uk),
        example_en=FieldValue.from_optional(
            preferred_example.en if preferred_example else None
        ),
        example_ru=FieldValue.from_optional(
            preferred_example.ru if preferred_example else None
        ),
    )


def filter_examples(examples: list[Example]) -> list[Example]:
    return [example for example in examples if rules.is_example_candidate(example.en)]


def _pick_preferred_example(
    current: Example | None,
    language_base_examples: list[Example],
) -> Example | None:
    paired = _select_example_with_ru(language_base_examples)
    if paired is not None:
        return paired
    fallback = _select_any_example(language_base_examples)
    if fallback is not None:
        return fallback
    return current


async def _language_base_examples_async(
    *,
    text: str,
    language_base: LanguageBase | None,
) -> list[Example]:
    if language_base is None or not language_base.is_available:
        return []
    try:
        examples = await asyncio.to_thread(
            language_base.get_examples,
            word=text,
            limit=_LANGUAGE_BASE_EXAMPLE_LIMIT,
        )
    except Exception:
        return []
    return filter_examples(list(examples))
