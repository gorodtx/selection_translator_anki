from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
import logging
import time
from collections.abc import Coroutine
from typing import Callable, Final

import aiohttp

from translate_logic.infrastructure.http.cache import HttpCache
from translate_logic.domain import rules
from translate_logic.domain.policies import SourcePolicy
from translate_logic.shared.example_selection import select_diverse_examples
from translate_logic.infrastructure.http.transport import (
    MAX_FAILURE_BACKOFF_ENTRIES,
    AsyncFetcher,
    FailureBackoffStore,
    build_async_fetcher,
)
from translate_logic.infrastructure.language_base.base import LanguageBase
from translate_logic.infrastructure.language_base.definitions_base import (
    DefinitionsBase,
)
from translate_logic.models import (
    Example,
    FieldValue,
    TranslationLimit,
    TranslationResult,
)
from translate_logic.infrastructure.providers.cambridge import (
    CambridgeResult,
    translate_cambridge,
)
from translate_logic.infrastructure.providers.google import (
    GoogleResult,
    translate_google,
)
from translate_logic.application.pipeline.ranking import (
    RankedTranslation,
    extract_ranked_texts,
    rank_translation_candidates,
)
from translate_logic.shared.text import (
    count_words,
    normalize_lookup_text,
    normalize_text,
    normalize_whitespace,
)
from translate_logic.shared.translation import (
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
    cambridge_en_timeout_s: float = 1.2
    cambridge_en_ru_timeout_s: float = 1.6
    google_timeout_s: float = 1.4
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
_GOOGLE_AUGMENT_TIMEOUT_S: Final[float] = 0.3
_GOOGLE_RECOVERY_TIMEOUT_S: Final[float] = 0.35
_GOOGLE_SECOND_RECOVERY_TIMEOUT_S: Final[float] = 0.75
_CAMBRIDGE_PRIMARY_WAIT_S: Final[float] = 0.02
_CAMBRIDGE_EMPTY_RECOVERY_WAIT_S: Final[float] = 0.25
_DEFINITIONS_LIMIT: Final[int] = 5
_DEFINITIONS_PRIMARY_LIMIT: Final[int] = 5
_DEFINITIONS_QUERY_MAX_WORDS: Final[int] = 5
_CAMBRIDGE_FALLBACK_MAX_WORDS: Final[int] = 5


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
    lookup_text: str | None = None,
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
            lookup_text,
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
            lookup_text,
            async_fetcher,
            language_base,
            definitions_base,
            on_partial,
        )


async def _translate_with_fetcher_async(
    text: str,
    source_lang: str,
    target_lang: str,
    lookup_text: str | None,
    fetcher: AsyncFetcher,
    language_base: LanguageBase | None = None,
    definitions_base: DefinitionsBase | None = None,
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    started = time.perf_counter()
    language_base_task: asyncio.Task[list[Example]] | None = None
    definitions_task: asyncio.Task[list[str]] | None = None
    try:
        network_text = text.strip()
        if not network_text:
            return TranslationResult.empty()
        resolved_lookup_text = normalize_lookup_text(lookup_text or network_text)
        if not resolved_lookup_text:
            return TranslationResult.empty()
        language_base_task = _start_lookup_task(
            _language_base_examples_async(
                text=resolved_lookup_text,
                language_base=language_base,
            )
        )
        definitions_task = _start_lookup_task(
            _definitions_base_defs_async(
                text=resolved_lookup_text,
                definitions_base=definitions_base,
            )
        )

        if _prefer_google_primary(resolved_lookup_text):
            return await _translate_google_primary_with_cambridge_best_effort_async(
                network_text=network_text,
                lookup_text=resolved_lookup_text,
                source_lang=source_lang,
                target_lang=target_lang,
                fetcher=fetcher,
                language_base_task=language_base_task,
                definitions_task=definitions_task,
                on_partial=on_partial,
            )

        word_count = count_words(resolved_lookup_text)
        if not _POLICY.use_cambridge(word_count):
            google_result = await _run_google_with_budget(
                network_text,
                source_lang,
                target_lang,
                fetcher,
            )
            google_candidates = select_translation_candidates(
                google_result.translations
            )
            translation_ru = _compose_ranked_translation(
                query=resolved_lookup_text,
                target_lang=target_lang,
                cambridge_translations=[],
                google_translations=google_candidates,
            )
            translation_ru = await _recover_empty_translation_async(
                text=network_text,
                ranking_query=resolved_lookup_text,
                source_lang=source_lang,
                target_lang=target_lang,
                fetcher=fetcher,
                current_translation=translation_ru,
                secondary_translations=[],
                attempt_id=2,
            )
            if not translation_ru and word_count > _CAMBRIDGE_FALLBACK_MAX_WORDS:
                translation_ru = await _recover_empty_translation_async(
                    text=network_text,
                    ranking_query=resolved_lookup_text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    fetcher=fetcher,
                    current_translation=translation_ru,
                    secondary_translations=[],
                    timeout_s=_GOOGLE_SECOND_RECOVERY_TIMEOUT_S,
                    attempt_id=3,
                )
            can_use_cambridge_fallback = word_count <= _CAMBRIDGE_FALLBACK_MAX_WORDS
            cambridge_google_fallback_result: CambridgeResult | None = None
            if not translation_ru and can_use_cambridge_fallback:
                cambridge_google_fallback_result = await _run_cambridge_with_budget(
                    resolved_lookup_text,
                    fetcher,
                )
                cambridge_candidates = select_translation_candidates(
                    cambridge_google_fallback_result.translations
                )
                translation_ru = _compose_ranked_translation(
                    query=resolved_lookup_text,
                    target_lang=target_lang,
                    cambridge_translations=cambridge_candidates,
                    google_translations=[],
                )
                if not translation_ru:
                    translation_ru = await _recover_empty_translation_async(
                        text=network_text,
                        ranking_query=resolved_lookup_text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        fetcher=fetcher,
                        current_translation=translation_ru,
                        secondary_translations=cambridge_candidates,
                        timeout_s=_GOOGLE_SECOND_RECOVERY_TIMEOUT_S,
                        attempt_id=4,
                    )
            _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
            _log_stage_elapsed("first_partial", _elapsed_ms(started))
            fallback_examples = await _resolve_examples_fallback(
                language_base_task,
                primary_count=len(
                    filter_examples(
                        cambridge_google_fallback_result.examples
                        if cambridge_google_fallback_result is not None
                        else []
                    )
                ),
            )
            examples_list = _merge_examples(
                primary=filter_examples(
                    cambridge_google_fallback_result.examples
                    if cambridge_google_fallback_result is not None
                    else []
                ),
                fallback=fallback_examples,
            )
            network_definitions = _merge_definition_sources(
                (
                    cambridge_google_fallback_result.definitions_en
                    if cambridge_google_fallback_result is not None
                    else []
                ),
                google_result.definitions_en,
            )
            fallback_definitions = await _resolve_definitions_fallback(
                definitions_task,
                primary_count=len(network_definitions),
            )
            return _build_result(
                translation_ru,
                examples=examples_list,
                definitions_en=_merge_definitions(
                    primary=network_definitions,
                    fallback=fallback_definitions,
                ),
            )

        google_prefetch_task: asyncio.Task[GoogleResult] = asyncio.create_task(
            _run_google_with_budget(network_text, source_lang, target_lang, fetcher)
        )
        cambridge_task: asyncio.Task[CambridgeResult] = asyncio.create_task(
            _run_cambridge_with_budget(resolved_lookup_text, fetcher)
        )
        cambridge_result = await _await_cambridge_prefetch(
            cambridge_task,
            timeout_s=_CAMBRIDGE_PRIMARY_WAIT_S,
        )

        if cambridge_result is None:
            prefetched_google_result = await _await_google_prefetch(
                google_prefetch_task
            )
            cambridge_empty_recovery_result: CambridgeResult | None = None
            google_empty = (
                prefetched_google_result is None
                or not prefetched_google_result.translations
            )
            if google_empty:
                cambridge_empty_recovery_result = await _await_cambridge_prefetch(
                    cambridge_task,
                    timeout_s=_CAMBRIDGE_EMPTY_RECOVERY_WAIT_S,
                )
            if not cambridge_task.done():
                cambridge_task.cancel()
                with suppress(asyncio.CancelledError):
                    await cambridge_task
            cambridge_recovery_translations = (
                select_translation_candidates(
                    cambridge_empty_recovery_result.translations
                )
                if cambridge_empty_recovery_result is not None
                else []
            )
            translation_ru = await _compose_translation_with_google_fallback_async(
                network_text=network_text,
                ranking_query=resolved_lookup_text,
                source_lang=source_lang,
                target_lang=target_lang,
                fetcher=fetcher,
                cambridge_translations=cambridge_recovery_translations,
                prefetched_google_result=prefetched_google_result,
            )
            _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
            _log_stage_elapsed("first_partial", _elapsed_ms(started))
            fallback_examples = await _resolve_examples_fallback(
                language_base_task,
                primary_count=len(
                    filter_examples(
                        cambridge_empty_recovery_result.examples
                        if cambridge_empty_recovery_result is not None
                        else []
                    )
                ),
            )
            examples_list = _merge_examples(
                primary=filter_examples(
                    cambridge_empty_recovery_result.examples
                    if cambridge_empty_recovery_result is not None
                    else []
                ),
                fallback=fallback_examples,
            )
            network_definitions = _merge_definition_sources(
                (
                    cambridge_empty_recovery_result.definitions_en
                    if cambridge_empty_recovery_result is not None
                    else []
                ),
                prefetched_google_result.definitions_en
                if prefetched_google_result is not None
                else [],
            )
            fallback_definitions = await _resolve_definitions_fallback(
                definitions_task,
                primary_count=len(network_definitions),
            )
            return _build_result(
                translation_ru,
                examples=examples_list,
                definitions_en=_merge_definitions(
                    primary=network_definitions,
                    fallback=fallback_definitions,
                ),
            )

        cambridge_non_meta, cambridge_meta = partition_translations(
            cambridge_result.translations
        )
        google_result_for_defs: GoogleResult | None = None
        google_ranked_candidates: list[str] = []
        if _needs_more_variants(cambridge_non_meta):
            google_augment_result = await _await_google_prefetch(
                google_prefetch_task,
                timeout_s=_GOOGLE_AUGMENT_TIMEOUT_S,
            )
            if google_augment_result is not None:
                google_result_for_defs = google_augment_result
                google_ranked_candidates = select_translation_candidates(
                    google_augment_result.translations
                )
        else:
            google_prefetch_task.cancel()
            with suppress(asyncio.CancelledError):
                await google_prefetch_task

        translation_ru = _compose_ranked_translation(
            query=resolved_lookup_text,
            target_lang=target_lang,
            cambridge_translations=merge_translations(
                cambridge_non_meta, cambridge_meta
            ),
            google_translations=google_ranked_candidates,
        )
        translation_ru = await _recover_empty_translation_async(
            text=network_text,
            ranking_query=resolved_lookup_text,
            source_lang=source_lang,
            target_lang=target_lang,
            fetcher=fetcher,
            current_translation=translation_ru,
            secondary_translations=cambridge_meta,
        )
        _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
        _log_stage_elapsed("first_partial", _elapsed_ms(started))
        fallback_examples = await _resolve_examples_fallback(
            language_base_task,
            primary_count=len(filter_examples(cambridge_result.examples)),
        )

        examples_list = _merge_examples(
            primary=filter_examples(cambridge_result.examples),
            fallback=fallback_examples,
        )
        network_definitions = _merge_definition_sources(
            cambridge_result.definitions_en,
            (
                google_result_for_defs.definitions_en
                if google_result_for_defs is not None
                else []
            ),
        )
        fallback_definitions = await _resolve_definitions_fallback(
            definitions_task,
            primary_count=len(network_definitions),
        )
        return _build_result(
            translation_ru,
            examples=examples_list,
            definitions_en=_merge_definitions(
                primary=network_definitions,
                fallback=fallback_definitions,
            ),
        )
    finally:
        await _cancel_lookup_task(language_base_task)
        await _cancel_lookup_task(definitions_task)
        _log_total_elapsed(_elapsed_ms(started))


async def _translate_google_primary_with_cambridge_best_effort_async(
    *,
    network_text: str,
    lookup_text: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    language_base_task: asyncio.Task[list[Example]] | None,
    definitions_task: asyncio.Task[list[str]] | None,
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    started = time.perf_counter()
    cambridge_task = asyncio.create_task(
        _run_cambridge_with_budget(lookup_text, fetcher)
    )
    google_result = await _run_google_with_budget(
        network_text,
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
        query=lookup_text,
        target_lang=target_lang,
        cambridge_translations=cambridge_candidates,
        google_translations=google_candidates,
    )
    _emit_partial(on_partial, FieldValue.from_optional(translation_ru))
    _log_stage_elapsed("first_partial", _elapsed_ms(started))
    fallback_examples = await _resolve_examples_fallback(
        language_base_task,
        primary_count=len(filter_examples(cambridge_result.examples)),
    )

    examples_list = _merge_examples(
        primary=filter_examples(cambridge_result.examples),
        fallback=fallback_examples,
    )
    network_definitions = _merge_definition_sources(
        cambridge_result.definitions_en,
        google_result.definitions_en,
    )
    fallback_definitions = await _resolve_definitions_fallback(
        definitions_task,
        primary_count=len(network_definitions),
    )
    return _build_result(
        translation_ru,
        examples=examples_list,
        definitions_en=_merge_definitions(
            primary=network_definitions,
            fallback=fallback_definitions,
        ),
    )


async def _compose_translation_with_google_fallback_async(
    *,
    network_text: str,
    ranking_query: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    cambridge_translations: list[str],
    prefetched_google_result: GoogleResult | None,
) -> str | None:
    google_result = prefetched_google_result
    if google_result is None:
        google_result = await _run_google_with_budget(
            network_text,
            source_lang,
            target_lang,
            fetcher,
        )
    google_candidates = select_translation_candidates(google_result.translations)
    translation_ru = _compose_ranked_translation(
        query=ranking_query,
        target_lang=target_lang,
        cambridge_translations=cambridge_translations,
        google_translations=google_candidates,
    )
    return await _recover_empty_translation_async(
        text=network_text,
        ranking_query=ranking_query,
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
    except asyncio.CancelledError:
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
    except asyncio.CancelledError:
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
    ranking_query: str,
    source_lang: str,
    target_lang: str,
    fetcher: AsyncFetcher,
    current_translation: str | None,
    secondary_translations: list[str] | None,
    allow_retry: bool = True,
    timeout_s: float = _GOOGLE_RECOVERY_TIMEOUT_S,
    attempt_id: int = 2,
) -> str | None:
    if current_translation or not allow_retry:
        return current_translation
    started = time.perf_counter()
    timed_out = False
    try:
        recovery = await asyncio.wait_for(
            translate_google(
                text,
                source_lang,
                target_lang,
                fetcher,
                attempt_id=attempt_id,
            ),
            timeout=timeout_s,
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
        query=ranking_query,
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


def _log_stage_elapsed(name: str, elapsed_ms: float) -> None:
    _LOGGER.debug("translation.%s.elapsed_ms=%.1f", name, elapsed_ms)


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


def _start_lookup_task[T](coroutine: Coroutine[object, object, T]) -> asyncio.Task[T]:
    return asyncio.create_task(coroutine)


async def _resolve_examples_fallback(
    task: asyncio.Task[list[Example]] | None,
    *,
    primary_count: int,
) -> list[Example]:
    if task is None:
        return []
    if primary_count >= _LANGUAGE_BASE_EXAMPLE_LIMIT:
        await _cancel_lookup_task(task)
        return []
    return await _resolve_lookup_task(task, default=[], label="examples")


async def _resolve_definitions_fallback(
    task: asyncio.Task[list[str]] | None,
    *,
    primary_count: int,
) -> list[str]:
    if task is None:
        return []
    if primary_count >= _DEFINITIONS_LIMIT:
        await _cancel_lookup_task(task)
        return []
    return await _resolve_lookup_task(task, default=[], label="definitions")


async def _resolve_lookup_task[T](
    task: asyncio.Task[T] | None,
    *,
    default: T,
    label: str,
) -> T:
    if task is None:
        return default
    started = time.perf_counter()
    try:
        return await task
    except asyncio.CancelledError:
        return default
    except Exception:
        return default
    finally:
        _log_stage_elapsed(f"lookup_{label}_wait", _elapsed_ms(started))


async def _cancel_lookup_task(task: asyncio.Task[object] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


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
        seed=_merge_examples_seed(merged_pool),
    )


async def warmup_pipeline_resources(
    *,
    language_base: LanguageBase | None,
    definitions_base: DefinitionsBase | None,
) -> None:
    if language_base is None and definitions_base is None:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        _LANGUAGE_BASE_EXECUTOR,
        partial(
            _warmup_pipeline_resources_sync,
            language_base=language_base,
            definitions_base=definitions_base,
        ),
    )


def _warmup_pipeline_resources_sync(
    *,
    language_base: LanguageBase | None,
    definitions_base: DefinitionsBase | None,
) -> None:
    if language_base is not None and language_base.is_available:
        with suppress(Exception):
            language_base.warmup()
    if definitions_base is not None and definitions_base.is_available:
        with suppress(Exception):
            definitions_base.warmup()


def _merge_examples_seed(examples: list[Example]) -> str:
    if not examples:
        return "merge:empty"
    parts = [normalize_whitespace(example.en).casefold() for example in examples]
    return "merge:" + "|".join(parts[:8])
