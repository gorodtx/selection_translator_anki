from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Final

from translate_logic.models import (
    ExamplePair,
    TranslationResult,
    TranslationVariant,
    VariantSource,
)
from translate_logic.providers.example_generator import ExampleGeneratorService
from translate_logic.providers.opus_mt import OpusMtProvider
from translate_logic.providers.reverso import translate_reverso
from translate_logic.text import normalize_text

DEFAULT_MIN_EXAMPLES: Final[int] = 2


async def translate_async(
    text: str,
    source_lang: str = "en",
    target_lang: str = "ru",
    *,
    opus_provider: OpusMtProvider | None = None,
    example_service: ExampleGeneratorService | None = None,
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return TranslationResult.empty()

    reverso_result = await translate_reverso(
        normalized_text,
        source_lang,
        target_lang,
    )
    variants = reverso_result.variants
    if not variants:
        variants = _fallback_opus_variant(
            normalized_text, source_lang, target_lang, opus_provider
        )

    if variants:
        _emit_partial(on_partial, variants)
    if not variants:
        return TranslationResult.empty()

    filled_variants = await _fill_examples_async(
        normalized_text,
        variants,
        example_service,
    )
    return TranslationResult(variants=filled_variants)


def _fallback_opus_variant(
    text: str,
    source_lang: str,
    target_lang: str,
    opus_provider: OpusMtProvider | None,
) -> tuple[TranslationVariant, ...]:
    if opus_provider is None:
        return ()
    translation = opus_provider.translate(text, source_lang, target_lang)
    if translation is None:
        return ()
    variant = TranslationVariant(
        ru=translation,
        pos=None,
        synonyms=(),
        examples=(),
        source=VariantSource.OPUS_MT,
    )
    return (variant,)


def _emit_partial(
    on_partial: Callable[[TranslationResult], None] | None,
    variants: tuple[TranslationVariant, ...],
) -> None:
    if on_partial is None:
        return
    stripped = tuple(_strip_examples(variant) for variant in variants)
    on_partial(TranslationResult(variants=stripped))


def _strip_examples(variant: TranslationVariant) -> TranslationVariant:
    return TranslationVariant(
        ru=variant.ru,
        pos=variant.pos,
        synonyms=variant.synonyms,
        examples=(),
        source=variant.source,
    )


def _merge_examples(
    existing: tuple[ExamplePair, ...],
    generated: tuple[ExamplePair, ...],
    limit: int,
) -> tuple[ExamplePair, ...]:
    if len(existing) >= limit:
        return existing[:limit]
    needed = limit - len(existing)
    return existing + generated[:needed]


def _fill_variant_examples(
    variant: TranslationVariant,
    generation: ExampleGeneratorService | None,
    text: str,
) -> TranslationVariant:
    if len(variant.examples) >= DEFAULT_MIN_EXAMPLES:
        return variant
    if generation is None:
        return variant
    result = generation.generate(text, variant.ru)
    merged = _merge_examples(variant.examples, result.examples, DEFAULT_MIN_EXAMPLES)
    return TranslationVariant(
        ru=variant.ru,
        pos=variant.pos,
        synonyms=variant.synonyms,
        examples=merged,
        source=variant.source,
    )


async def _fill_examples_async(
    text: str,
    variants: tuple[TranslationVariant, ...],
    example_service: ExampleGeneratorService | None,
) -> tuple[TranslationVariant, ...]:
    if not variants:
        return ()
    if example_service is None:
        return variants
    filled: list[TranslationVariant] = []
    for variant in variants:
        updated = await asyncio.to_thread(
            _fill_variant_examples,
            variant,
            example_service,
            text,
        )
        filled.append(updated)
    return tuple(filled)
