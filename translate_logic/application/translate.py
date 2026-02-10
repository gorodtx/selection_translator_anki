from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging
import time
from typing import Callable, Final

import aiohttp

from translate_logic.cache import LruTtlCache
from translate_logic.domain import rules
from translate_logic.domain.policies import SourcePolicy
from translate_logic.http import (
    MAX_FAILURE_BACKOFF_ENTRIES,
    AsyncFetcher,
    FailureBackoffStore,
    build_async_fetcher,
)
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
_LOGGER = logging.getLogger(__name__)
_FAILURE_BACKOFF_SECONDS: Final[float] = 30.0
_FAILURE_BACKOFF_STORE = FailureBackoffStore(
    ttl_seconds=_FAILURE_BACKOFF_SECONDS,
    max_entries=MAX_FAILURE_BACKOFF_ENTRIES,
)


@dataclass(frozen=True, slots=True)
class ProviderBudget:
    cambridge_en_timeout_s: float = 1.5
    cambridge_en_ru_timeout_s: float = 2.0
    google_timeout_s: float = 2.2
    dictionary_timeout_s: float = 0.4
    tatoeba_timeout_s: float = 0.9
    overall_budget_s: float = 4.0


_PROVIDER_BUDGET: Final[ProviderBudget] = ProviderBudget()
_PROVIDER_TIMEOUTS_BY_HOST: Final[dict[str, float]] = {
    "dictionary.cambridge.org": _PROVIDER_BUDGET.cambridge_en_ru_timeout_s,
    "translate.googleapis.com": _PROVIDER_BUDGET.google_timeout_s,
    "api.dictionaryapi.dev": _PROVIDER_BUDGET.dictionary_timeout_s,
    "api.tatoeba.org": _PROVIDER_BUDGET.tatoeba_timeout_s,
}
_PROVIDER_TIMEOUTS_BY_PATTERN: Final[tuple[tuple[str, float], ...]] = (
    ("datasetsearch=english-russian", _PROVIDER_BUDGET.cambridge_en_ru_timeout_s),
    ("datasetsearch=english", _PROVIDER_BUDGET.cambridge_en_timeout_s),
)
_HIGH_AMBIGUITY_TOKENS: Final[set[str]] = {"a", "i", "x"}
_GOOGLE_AUGMENT_TIMEOUT_S: Final[float] = 0.35
_EXAMPLE_TRANSLATION_TIMEOUT_S: Final[float] = 0.1
_GOOGLE_RECOVERY_TIMEOUT_S: Final[float] = 2.2
_CAMBRIDGE_PRIMARY_WAIT_S: Final[float] = 0.25
_SUPPLEMENT_WAIT_S: Final[float] = 0.08


def build_latency_fetcher(
    session: aiohttp.ClientSession,
    *,
    cache: LruTtlCache | None = DEFAULT_CACHE,
) -> AsyncFetcher:
    return build_async_fetcher(
        session,
        cache=cache,
        timeout=_PROVIDER_BUDGET.overall_budget_s,
        timeouts_by_host=_PROVIDER_TIMEOUTS_BY_HOST,
        timeouts_by_pattern=_PROVIDER_TIMEOUTS_BY_PATTERN,
        failure_backoff_seconds=_FAILURE_BACKOFF_SECONDS,
        failure_backoff_store=_FAILURE_BACKOFF_STORE,
    )


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
        async_fetcher = build_latency_fetcher(session, cache=DEFAULT_CACHE)
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
    started = time.perf_counter()
    try:
        normalized_text = normalize_text(text)
        if not normalized_text:
            return TranslationResult.empty()
        language_base_examples = await _language_base_examples_async(
            text=normalized_text,
            language_base=language_base,
        )

        if _prefer_google_primary(normalized_text):
            return await _translate_google_primary_with_cambridge_best_effort_async(
                normalized_text,
                source_lang,
                target_lang,
                fetcher,
                language_base_examples,
                on_partial,
            )

        word_count = count_words(normalized_text)
        if not _POLICY.use_cambridge(word_count):
            cambridge_result = CambridgeResult(
                found=False,
                translations=[],
                ipa_uk=None,
                examples=[],
            )
            (
                translation_ru,
                ipa_uk,
                example,
            ) = await _translate_with_google_fallback_async(
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

        google_prefetch_task: asyncio.Task[GoogleResult] = asyncio.create_task(
            _run_google_with_budget(normalized_text, source_lang, target_lang, fetcher)
        )
        cambridge_task: asyncio.Task[CambridgeResult] = asyncio.create_task(
            _run_cambridge_with_budget(normalized_text, fetcher)
        )
        cambridge_result = await _await_cambridge_prefetch(
            cambridge_task,
            timeout_s=_CAMBRIDGE_PRIMARY_WAIT_S,
        )
        if cambridge_result is None:
            prefetched_google_result = await _await_google_prefetch(
                google_prefetch_task
            )
            if not cambridge_task.done():
                cambridge_task.cancel()
                with suppress(asyncio.CancelledError):
                    await cambridge_task
            (
                translation_ru,
                ipa_uk,
                example,
            ) = await _translate_with_google_fallback_async(
                normalized_text,
                CambridgeResult(
                    found=False,
                    translations=[],
                    ipa_uk=None,
                    examples=[],
                ),
                source_lang,
                target_lang,
                fetcher,
                language_base_examples,
                on_partial,
                prefetched_google_result=prefetched_google_result,
            )
            return _build_result(
                translation_ru,
                ipa_uk,
                example,
                language_base_examples=language_base_examples,
            )

        if cambridge_result.found:
            cambridge_non_meta, cambridge_meta = partition_translations(
                cambridge_result.translations
            )
            if cambridge_non_meta:
                translation_ru = combine_translation_variants(cambridge_non_meta, [])
                _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
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
                if _needs_more_variants(cambridge_non_meta):
                    google_result = await _await_google_prefetch(
                        google_prefetch_task,
                        timeout_s=_GOOGLE_AUGMENT_TIMEOUT_S,
                    )
                    if google_result is not None:
                        google_candidates = select_translation_candidates(
                            google_result.translations
                        )
                        if google_candidates:
                            translation_ru = combine_translation_variants(
                                cambridge_non_meta, google_candidates
                            )
                else:
                    google_prefetch_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await google_prefetch_task
                ipa_uk, example = await _await_supplement_task(
                    ipa_task,
                    fallback_ipa=cambridge_result.ipa_uk,
                    fallback_examples=cambridge_result.examples,
                    language_base_examples=language_base_examples,
                )
                return _build_result(
                    translation_ru,
                    ipa_uk,
                    example,
                    language_base_examples=language_base_examples,
                )
            prefetched_google_result = await _await_google_prefetch(
                google_prefetch_task
            )
            (
                translation_ru,
                ipa_uk,
                example,
            ) = await _translate_with_google_fallback_async(
                normalized_text,
                cambridge_result,
                source_lang,
                target_lang,
                fetcher,
                language_base_examples,
                on_partial,
                secondary_translations=cambridge_meta,
                prefetched_google_result=prefetched_google_result,
            )
            return _build_result(
                translation_ru,
                ipa_uk,
                example,
                language_base_examples=language_base_examples,
            )

        prefetched_google_result = await _await_google_prefetch(google_prefetch_task)
        translation_ru, ipa_uk, example = await _translate_with_google_fallback_async(
            normalized_text,
            cambridge_result,
            source_lang,
            target_lang,
            fetcher,
            language_base_examples,
            on_partial,
            prefetched_google_result=prefetched_google_result,
        )
        return _build_result(
            translation_ru,
            ipa_uk,
            example,
            language_base_examples=language_base_examples,
        )
    finally:
        _log_total_elapsed(_elapsed_ms(started))


async def _translate_google_primary_with_cambridge_best_effort_async(
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    language_base_examples: list[Example],
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    cambridge_task = asyncio.create_task(_run_cambridge_with_budget(text, fetcher))
    google_result = await _run_google_with_budget(
        text, source_lang, target_lang, fetcher
    )
    google_candidates = select_translation_candidates(google_result.translations)
    translation_ru = combine_translation_variants(google_candidates, [])
    _emit_partial(on_partial, FieldValue.from_optional(translation_ru))

    cambridge_result = CambridgeResult(
        found=False,
        translations=[],
        ipa_uk=None,
        examples=[],
    )
    if cambridge_task.done():
        with suppress(Exception):
            cambridge_result = cambridge_task.result()
    else:
        cambridge_task.cancel()
        with suppress(asyncio.CancelledError):
            await cambridge_task

    supplement_task = asyncio.create_task(
        _supplement_pronunciation_and_examples_async(
            text,
            cambridge_result.ipa_uk,
            cambridge_result.examples,
            source_lang,
            target_lang,
            fetcher,
            language_base_examples,
        )
    )
    ipa_uk, example = await _await_supplement_task(
        supplement_task,
        fallback_ipa=cambridge_result.ipa_uk,
        fallback_examples=cambridge_result.examples,
        language_base_examples=language_base_examples,
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
    prefetched_google_result: GoogleResult | None = None,
) -> tuple[str | None, str | None, Example | None]:
    base_ipa = cambridge_result.ipa_uk if cambridge_result.found else None
    base_examples = (
        filter_examples(cambridge_result.examples) if cambridge_result.found else []
    )
    supplement_task = asyncio.create_task(
        _supplement_pronunciation_and_examples_async(
            text,
            base_ipa,
            base_examples,
            source_lang,
            target_lang,
            fetcher,
            language_base_examples=language_base_examples,
        )
    )
    google_result = prefetched_google_result
    if google_result is None:
        google_result = await _run_google_with_budget(
            text,
            source_lang,
            target_lang,
            fetcher,
        )
    google_candidates = (
        select_translation_candidates(google_result.translations)
        if google_result is not None
        else []
    )
    translation_ru = combine_translation_variants(
        google_candidates, secondary_translations or []
    )
    translation_ru = await _recover_empty_translation_async(
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        fetcher=fetcher,
        current_translation=translation_ru,
        secondary_translations=secondary_translations,
    )
    _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
    ipa_uk, example = await _await_supplement_task(
        supplement_task,
        fallback_ipa=base_ipa,
        fallback_examples=base_examples,
        language_base_examples=language_base_examples,
    )
    return translation_ru, ipa_uk, example


async def _supplement_pronunciation_and_examples_async(
    text: str,
    ipa_uk: str | None,
    examples: list[Example],
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    language_base_examples: list[Example] | None = None,
) -> tuple[str | None, Example | None]:
    available_examples = filter_examples(examples)
    local_examples = filter_examples(language_base_examples or [])
    paired_local_example = _select_example_with_ru(local_examples)
    paired_available_example = _select_example_with_ru(available_examples)
    if paired_local_example is not None and ipa_uk is not None:
        return ipa_uk, paired_local_example
    if paired_available_example is not None and ipa_uk is not None:
        return ipa_uk, paired_available_example

    needs_dictionary = _POLICY.needs_dictionary(ipa_uk, available_examples)
    needs_tatoeba = not available_examples
    if paired_local_example is not None:
        needs_tatoeba = False

    dictionary_result = None
    tatoeba_result = None
    dictionary_task = (
        asyncio.create_task(_run_dictionary_with_budget(text, fetcher))
        if needs_dictionary
        else None
    )
    tatoeba_task = (
        asyncio.create_task(_run_tatoeba_with_budget(text, fetcher))
        if needs_tatoeba
        else None
    )

    if dictionary_task is not None:
        dictionary_result = await dictionary_task
    if dictionary_result is not None:
        if ipa_uk is None:
            ipa_uk = dictionary_result.ipa_uk
        if not available_examples:
            available_examples = filter_examples(dictionary_result.examples)
            paired_available_example = _select_example_with_ru(available_examples)

    if tatoeba_task is not None:
        tatoeba_result = await tatoeba_task

    if paired_local_example is not None:
        return ipa_uk, paired_local_example

    paired_example = paired_available_example
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
        translated = await _run_google_example_with_budget(
            final_example.en,
            source_lang,
            target_lang,
            fetcher,
        )
        if translated is not None:
            translation_ru = select_primary_translation(translated.translations)
            if translation_ru:
                final_example = Example(en=final_example.en, ru=translation_ru)

    return ipa_uk, final_example


def _prefer_google_primary(text: str) -> bool:
    normalized = text.strip().casefold()
    if len(normalized) <= 1:
        return True
    return normalized in _HIGH_AMBIGUITY_TOKENS


async def _await_google_prefetch(
    task: asyncio.Task[GoogleResult],
    *,
    timeout_s: float | None = None,
) -> GoogleResult | None:
    try:
        if timeout_s is None:
            return await task
        return await asyncio.wait_for(task, timeout=timeout_s)
    except TimeoutError:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return None
    except Exception:
        return None


async def _await_cambridge_prefetch(
    task: asyncio.Task[CambridgeResult],
    *,
    timeout_s: float,
) -> CambridgeResult | None:
    try:
        return await asyncio.wait_for(task, timeout=timeout_s)
    except TimeoutError:
        return None
    except Exception:
        return None


async def _await_supplement_task(
    task: asyncio.Task[tuple[str | None, Example | None]],
    *,
    fallback_ipa: str | None,
    fallback_examples: list[Example],
    language_base_examples: list[Example] | None,
) -> tuple[str | None, Example | None]:
    try:
        return await asyncio.wait_for(task, timeout=_SUPPLEMENT_WAIT_S)
    except TimeoutError:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        fallback = _pick_preferred_example(
            _select_any_example(filter_examples(fallback_examples)),
            filter_examples(language_base_examples or []),
        )
        return fallback_ipa, fallback
    except Exception:
        fallback = _pick_preferred_example(
            _select_any_example(filter_examples(fallback_examples)),
            filter_examples(language_base_examples or []),
        )
        return fallback_ipa, fallback


async def _run_cambridge_with_budget(
    text: str,
    fetcher: AsyncFetcher,
) -> CambridgeResult:
    started = time.perf_counter()
    timed_out = False
    try:
        return await asyncio.wait_for(
            translate_cambridge(text, fetcher),
            timeout=_PROVIDER_BUDGET.cambridge_en_ru_timeout_s,
        )
    except TimeoutError:
        timed_out = True
        return CambridgeResult(
            found=False,
            translations=[],
            ipa_uk=None,
            examples=[],
        )
    except Exception:
        return CambridgeResult(
            found=False,
            translations=[],
            ipa_uk=None,
            examples=[],
        )
    finally:
        _log_provider_elapsed("cambridge", _elapsed_ms(started), timed_out)


async def _run_google_with_budget(
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
) -> GoogleResult:
    started = time.perf_counter()
    timed_out = False
    try:
        return await asyncio.wait_for(
            translate_google(text, source_lang, target_lang, fetcher),
            timeout=_PROVIDER_BUDGET.google_timeout_s,
        )
    except TimeoutError:
        timed_out = True
        return GoogleResult(translations=[])
    except Exception:
        return GoogleResult(translations=[])
    finally:
        _log_provider_elapsed("google", _elapsed_ms(started), timed_out)


async def _run_google_example_with_budget(
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
) -> GoogleResult | None:
    try:
        return await asyncio.wait_for(
            _run_google_with_budget(text, source_lang, target_lang, fetcher),
            timeout=_EXAMPLE_TRANSLATION_TIMEOUT_S,
        )
    except TimeoutError:
        return None
    except Exception:
        return None


async def _recover_empty_translation_async(
    *,
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    current_translation: str | None,
    secondary_translations: list[str] | None,
) -> str | None:
    if current_translation:
        return current_translation
    started = time.perf_counter()
    timed_out = False
    try:
        recovery = await asyncio.wait_for(
            translate_google(text, source_lang, target_lang, fetcher),
            timeout=_GOOGLE_RECOVERY_TIMEOUT_S,
        )
    except TimeoutError:
        timed_out = True
        return current_translation
    except Exception:
        return current_translation
    finally:
        _log_provider_elapsed("google_recovery", _elapsed_ms(started), timed_out)
    recovery_candidates = select_translation_candidates(recovery.translations)
    recovered = combine_translation_variants(
        recovery_candidates,
        secondary_translations or [],
    )
    return recovered or current_translation


async def _run_dictionary_with_budget(
    text: str,
    fetcher: AsyncFetcher,
) -> DictionaryApiResult:
    started = time.perf_counter()
    timed_out = False
    try:
        return await asyncio.wait_for(
            translate_dictionary_api(text, fetcher),
            timeout=_PROVIDER_BUDGET.dictionary_timeout_s,
        )
    except TimeoutError:
        timed_out = True
        return DictionaryApiResult(ipa_uk=None, examples=[])
    except Exception:
        return DictionaryApiResult(ipa_uk=None, examples=[])
    finally:
        _log_provider_elapsed("dictionary", _elapsed_ms(started), timed_out)


async def _run_tatoeba_with_budget(
    text: str,
    fetcher: AsyncFetcher,
) -> TatoebaResult:
    started = time.perf_counter()
    timed_out = False
    try:
        return await asyncio.wait_for(
            translate_tatoeba(text, fetcher),
            timeout=_PROVIDER_BUDGET.tatoeba_timeout_s,
        )
    except TimeoutError:
        timed_out = True
        return TatoebaResult(examples=[])
    except Exception:
        return TatoebaResult(examples=[])
    finally:
        _log_provider_elapsed("tatoeba", _elapsed_ms(started), timed_out)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _log_provider_elapsed(name: str, elapsed_ms: float, timed_out: bool) -> None:
    _LOGGER.debug(
        "provider.%s.elapsed_ms=%.1f provider.%s.timeout_count=%d",
        name,
        elapsed_ms,
        name,
        1 if timed_out else 0,
    )


def _log_total_elapsed(elapsed_ms: float) -> None:
    _LOGGER.debug("translation.total.elapsed_ms=%.1f", elapsed_ms)


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
