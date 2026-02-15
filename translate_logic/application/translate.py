from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
import logging
import time
from typing import Callable, Final

import aiohttp

from translate_logic.cache import HttpCache
from translate_logic.domain import rules
from translate_logic.domain.policies import SourcePolicy
from translate_logic.example_selection import select_diverse_examples
from translate_logic.http import (
    MAX_FAILURE_BACKOFF_ENTRIES,
    AsyncFetcher,
    FailureBackoffStore,
    build_async_fetcher,
)
from translate_logic.language_base.base import LanguageBase
from translate_logic.language_base.definitions_base import DefinitionsBase
from translate_logic.models import (
    Example,
    FieldValue,
    TranslationLimit,
    TranslationResult,
)
from translate_logic.providers.cambridge import CambridgeResult, translate_cambridge
from translate_logic.providers.google import GoogleResult, translate_google
from translate_logic.ranking import (
    RankedTranslation,
    extract_ranked_texts,
    rank_translation_candidates,
)
from translate_logic.text import count_words, normalize_text, normalize_whitespace
from translate_logic.translation import (
    limit_translations,
    merge_translations,
    partition_translations,
    select_translation_candidates,
)

DEFAULT_CACHE = HttpCache()
_POLICY = SourcePolicy()
_LANGUAGE_BASE_EXAMPLE_LIMIT = 4
_LANGUAGE_BASE_EXECUTOR: Final[ThreadPoolExecutor] = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="translator-langbase",
)
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
    overall_budget_s: float = 4.0


_PROVIDER_BUDGET: Final[ProviderBudget] = ProviderBudget()
_PROVIDER_TIMEOUTS_BY_HOST: Final[dict[str, float]] = {
    "dictionary.cambridge.org": _PROVIDER_BUDGET.cambridge_en_ru_timeout_s,
    "translate.googleapis.com": _PROVIDER_BUDGET.google_timeout_s,
}
_PROVIDER_TIMEOUTS_BY_PATTERN: Final[tuple[tuple[str, float], ...]] = (
    ("datasetsearch=english-russian", _PROVIDER_BUDGET.cambridge_en_ru_timeout_s),
    ("datasetsearch=english", _PROVIDER_BUDGET.cambridge_en_timeout_s),
)
_HIGH_AMBIGUITY_TOKENS: Final[set[str]] = {"a", "i", "x"}
_GOOGLE_AUGMENT_TIMEOUT_S: Final[float] = 0.35
_GOOGLE_RECOVERY_TIMEOUT_S: Final[float] = 2.2
_CAMBRIDGE_PRIMARY_WAIT_S: Final[float] = 0.25
_DEFINITIONS_LIMIT: Final[int] = 5
_DEFINITIONS_PRIMARY_LIMIT: Final[int] = 5
_DEFINITIONS_QUERY_MAX_WORDS: Final[int] = 5


def build_latency_fetcher(
    session: aiohttp.ClientSession,
    *,
    cache: HttpCache | None = DEFAULT_CACHE,
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
    definitions_base: DefinitionsBase | None = None,
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    if fetcher is not None:
        return await _translate_with_fetcher_async(
            text,
            source_lang,
            target_lang,
            fetcher,
            language_base,
            definitions_base,
            on_partial,
        )
    async with aiohttp.ClientSession() as session:
        async_fetcher = build_latency_fetcher(session, cache=DEFAULT_CACHE)
        return await _translate_with_fetcher_async(
            text,
            source_lang,
            target_lang,
            async_fetcher,
            language_base,
            definitions_base,
            on_partial,
        )


async def _translate_with_fetcher_async(
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    language_base: LanguageBase | None = None,
    definitions_base: DefinitionsBase | None = None,
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
        definitions_base_defs = await _definitions_base_defs_async(
            text=normalized_text,
            definitions_base=definitions_base,
        )

        if _prefer_google_primary(normalized_text):
            return await _translate_google_primary_with_cambridge_best_effort_async(
                normalized_text,
                source_lang,
                target_lang,
                fetcher,
                language_base_examples,
                definitions_base_defs,
                on_partial,
            )

        word_count = count_words(normalized_text)
        if not _POLICY.use_cambridge(word_count):
            google_result = await _run_google_with_budget(
                normalized_text,
                source_lang,
                target_lang,
                fetcher,
            )
            google_candidates = select_translation_candidates(
                google_result.translations
            )
            translation_ru = _compose_ranked_translation(
                query=normalized_text,
                target_lang=target_lang,
                cambridge_translations=[],
                google_translations=google_candidates,
            )
            translation_ru = await _recover_empty_translation_async(
                text=normalized_text,
                source_lang=source_lang,
                target_lang=target_lang,
                fetcher=fetcher,
                current_translation=translation_ru,
                secondary_translations=[],
            )
            _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
            examples_list = _merge_examples(
                primary=filter_examples([]),
                fallback=language_base_examples,
            )
            network_definitions = _merge_definition_sources(
                google_result.definitions_en
            )
            return _build_result(
                translation_ru,
                examples=examples_list,
                definitions_en=_merge_definitions(
                    primary=network_definitions,
                    fallback=definitions_base_defs,
                ),
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
            translation_ru = await _compose_translation_with_google_fallback_async(
                text=normalized_text,
                source_lang=source_lang,
                target_lang=target_lang,
                fetcher=fetcher,
                cambridge_translations=[],
                prefetched_google_result=prefetched_google_result,
            )
            _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
            examples_list = _merge_examples(
                primary=filter_examples([]),
                fallback=language_base_examples,
            )
            network_definitions = _merge_definition_sources(
                prefetched_google_result.definitions_en
                if prefetched_google_result is not None
                else []
            )
            return _build_result(
                translation_ru,
                examples=examples_list,
                definitions_en=_merge_definitions(
                    primary=network_definitions,
                    fallback=definitions_base_defs,
                ),
            )

        cambridge_non_meta, cambridge_meta = partition_translations(
            cambridge_result.translations
        )
        google_result_for_defs: GoogleResult | None = None
        google_candidates: list[str] = []
        if _needs_more_variants(cambridge_non_meta):
            google_result = await _await_google_prefetch(
                google_prefetch_task,
                timeout_s=_GOOGLE_AUGMENT_TIMEOUT_S,
            )
            if google_result is not None:
                google_result_for_defs = google_result
                google_candidates = select_translation_candidates(
                    google_result.translations
                )
        else:
            google_prefetch_task.cancel()
            with suppress(asyncio.CancelledError):
                await google_prefetch_task

        translation_ru = _compose_ranked_translation(
            query=normalized_text,
            target_lang=target_lang,
            cambridge_translations=merge_translations(
                cambridge_non_meta, cambridge_meta
            ),
            google_translations=google_candidates,
        )
        translation_ru = await _recover_empty_translation_async(
            text=normalized_text,
            source_lang=source_lang,
            target_lang=target_lang,
            fetcher=fetcher,
            current_translation=translation_ru,
            secondary_translations=cambridge_meta,
        )
        _emit_partial(on_partial, FieldValue.from_optional(translation_ru))

        examples_list = _merge_examples(
            primary=filter_examples(cambridge_result.examples),
            fallback=language_base_examples,
        )
        network_definitions = _merge_definition_sources(
            cambridge_result.definitions_en,
            (
                google_result_for_defs.definitions_en
                if google_result_for_defs is not None
                else []
            ),
        )
        return _build_result(
            translation_ru,
            examples=examples_list,
            definitions_en=_merge_definitions(
                primary=network_definitions,
                fallback=definitions_base_defs,
            ),
        )
    finally:
        _log_total_elapsed(_elapsed_ms(started))


async def _translate_google_primary_with_cambridge_best_effort_async(
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    language_base_examples: list[Example],
    definitions_base_defs: list[str],
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    cambridge_task = asyncio.create_task(_run_cambridge_with_budget(text, fetcher))
    google_result = await _run_google_with_budget(
        text,
        source_lang,
        target_lang,
        fetcher,
    )
    google_candidates = select_translation_candidates(google_result.translations)

    cambridge_result = CambridgeResult(
        found=False,
        translations=[],
        examples=[],
        definitions_en=[],
    )
    if cambridge_task.done():
        with suppress(Exception):
            cambridge_result = cambridge_task.result()
    else:
        cambridge_task.cancel()
        with suppress(asyncio.CancelledError):
            await cambridge_task

    cambridge_candidates = select_translation_candidates(cambridge_result.translations)
    translation_ru = _compose_ranked_translation(
        query=text,
        target_lang=target_lang,
        cambridge_translations=cambridge_candidates,
        google_translations=google_candidates,
    )
    _emit_partial(on_partial, FieldValue.from_optional(translation_ru))

    examples_list = _merge_examples(
        primary=filter_examples(cambridge_result.examples),
        fallback=language_base_examples,
    )
    network_definitions = _merge_definition_sources(
        cambridge_result.definitions_en,
        google_result.definitions_en,
    )
    return _build_result(
        translation_ru,
        examples=examples_list,
        definitions_en=_merge_definitions(
            primary=network_definitions,
            fallback=definitions_base_defs,
        ),
    )


async def _compose_translation_with_google_fallback_async(
    *,
    text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    cambridge_translations: list[str],
    prefetched_google_result: GoogleResult | None,
) -> str | None:
    google_result = prefetched_google_result
    if google_result is None:
        google_result = await _run_google_with_budget(
            text,
            source_lang,
            target_lang,
            fetcher,
        )
    google_candidates = select_translation_candidates(google_result.translations)
    translation_ru = _compose_ranked_translation(
        query=text,
        target_lang=target_lang,
        cambridge_translations=cambridge_translations,
        google_translations=google_candidates,
    )
    return await _recover_empty_translation_async(
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        fetcher=fetcher,
        current_translation=translation_ru,
        secondary_translations=cambridge_translations,
    )


def _compose_ranked_translation(
    *,
    query: str,
    target_lang: str,
    cambridge_translations: list[str],
    google_translations: list[str],
) -> str | None:
    ranked = rank_translation_candidates(
        query,
        cambridge=cambridge_translations,
        google=google_translations,
        target_lang=target_lang,
        limit=TranslationLimit.PRIMARY.value,
    )
    if not ranked:
        return None
    _log_ranked_candidates(query, ranked)
    ranked_texts = extract_ranked_texts(ranked)
    if not ranked_texts:
        return None
    return "; ".join(ranked_texts)


def _log_ranked_candidates(query: str, ranked: list[RankedTranslation]) -> None:
    preview = [
        {
            "text": item.text,
            "source": item.source.value,
            "score": round(item.score, 3),
        }
        for item in ranked[:3]
    ]
    _LOGGER.debug("ranking.query=%r ranking.top=%s", query, preview)


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
            examples=[],
            definitions_en=[],
        )
    except Exception:
        return CambridgeResult(
            found=False,
            translations=[],
            examples=[],
            definitions_en=[],
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
        return GoogleResult(translations=[], definitions_en=[])
    except Exception:
        return GoogleResult(translations=[], definitions_en=[])
    finally:
        _log_provider_elapsed("google", _elapsed_ms(started), timed_out)


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
    recovered = _compose_ranked_translation(
        query=text,
        target_lang=target_lang,
        cambridge_translations=secondary_translations or [],
        google_translations=recovery_candidates,
    )
    return recovered or current_translation


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
            definitions_en=(),
            examples=(),
        )
    )


def _needs_more_variants(translations: list[str]) -> bool:
    unique = merge_translations(translations, [])
    limited = limit_translations(unique, TranslationLimit.PRIMARY.value)
    return len(limited) < TranslationLimit.PRIMARY.value


def _build_result(
    translation_ru: str | None,
    *,
    examples: list[Example] | None = None,
    definitions_en: list[str] | None = None,
) -> TranslationResult:
    resolved_examples = examples or []
    return TranslationResult(
        translation_ru=FieldValue.from_optional(translation_ru),
        definitions_en=_normalize_definitions(definitions_en),
        examples=tuple(resolved_examples),
    )


def filter_examples(examples: list[Example]) -> list[Example]:
    return [example for example in examples if rules.is_example_candidate(example.en)]


def _merge_definitions(*, primary: list[str], fallback: list[str]) -> list[str]:
    if not primary:
        return fallback
    if not fallback:
        return primary
    return [*primary, *fallback]


def _merge_definition_sources(*sources: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for item in source:
            normalized = normalize_whitespace(item)
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return merged


def _normalize_definitions(definitions: list[str] | None) -> tuple[str, ...]:
    if not definitions:
        return ()
    seen: set[str] = set()
    normalized_values: list[str] = []
    for item in definitions:
        normalized = normalize_whitespace(item)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_values.append(normalized)
        if len(normalized_values) >= _DEFINITIONS_LIMIT:
            break
    return tuple(normalized_values)


async def _language_base_examples_async(
    *,
    text: str,
    language_base: LanguageBase | None,
) -> list[Example]:
    if language_base is None or not language_base.is_available:
        return []
    normalized = normalize_text(text)
    if count_words(normalized) == 1:
        token = normalized.casefold()
        if len(token) <= 2 or token in _HIGH_AMBIGUITY_TOKENS:
            return []
    try:
        loop = asyncio.get_running_loop()
        fetch_examples = partial(
            language_base.get_examples,
            word=normalized,
            limit=_LANGUAGE_BASE_EXAMPLE_LIMIT,
        )
        examples = await loop.run_in_executor(_LANGUAGE_BASE_EXECUTOR, fetch_examples)
    except Exception:
        return []
    return filter_examples(list(examples))


async def _definitions_base_defs_async(
    *,
    text: str,
    definitions_base: DefinitionsBase | None,
) -> list[str]:
    if definitions_base is None or not definitions_base.is_available:
        return []
    if count_words(text) > _DEFINITIONS_QUERY_MAX_WORDS:
        return []
    try:
        loop = asyncio.get_running_loop()
        fetch_defs = partial(
            definitions_base.get_definitions,
            word=text,
            limit=_DEFINITIONS_PRIMARY_LIMIT,
        )
        definitions = await loop.run_in_executor(_LANGUAGE_BASE_EXECUTOR, fetch_defs)
    except Exception:
        return []
    return list(definitions)


def _merge_examples(
    *, primary: list[Example], fallback: list[Example]
) -> list[Example]:
    merged_pool: list[Example] = []
    for example in [*primary, *fallback]:
        if not example.en:
            continue
        merged_pool.append(example)
    return select_diverse_examples(
        merged_pool,
        limit=_LANGUAGE_BASE_EXAMPLE_LIMIT,
        seed=f"merge:{time.time_ns()}",
    )
