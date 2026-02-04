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
from translate_logic.providers.fallback_examples import build_fallback_examples
from translate_logic.language_base.base import LanguageBase
from translate_logic.providers.opus_mt import OpusMtProvider
from translate_logic.text import normalize_text

DEFAULT_MIN_EXAMPLES: Final[int] = 2
DEFAULT_VARIANTS: Final[int] = 3


async def translate_async(
    text: str,
    source_lang: str = "en",
    target_lang: str = "ru",
    *,
    opus_provider: OpusMtProvider | None = None,
    language_base: LanguageBase | None = None,
    on_partial: Callable[[TranslationResult], None] | None = None,
) -> TranslationResult:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return TranslationResult.empty()

    variants = _variants_from_language_base(normalized_text, language_base)
    if not variants:
        variants = _fallback_opus_variant(
            normalized_text, source_lang, target_lang, opus_provider
        )
    if not variants:
        return TranslationResult.empty()

    _emit_partial(on_partial, variants)
    filled_variants = await _fill_examples_async(
        normalized_text,
        variants,
        language_base,
    )
    return TranslationResult(variants=filled_variants)


def _variants_from_language_base(
    text: str, language_base: LanguageBase | None
) -> tuple[TranslationVariant, ...]:
    if language_base is None:
        return ()
    # Variants make sense mostly for word/short phrase lookup.
    if len(text) > 64:
        return ()
    if text.count(" ") > 3:
        return ()
    ru_variants = language_base.get_variants(word=text, limit=DEFAULT_VARIANTS)
    if not ru_variants:
        return ()
    return tuple(
        TranslationVariant(
            ru=item,
            pos=None,
            synonyms=(),
            examples=(),
            source=VariantSource.OPUS_OPEN_SUBTITLES,
        )
        for item in ru_variants
    )


def _fallback_opus_variant(
    text: str,
    source_lang: str,
    target_lang: str,
    opus_provider: OpusMtProvider | None,
) -> tuple[TranslationVariant, ...]:
    if opus_provider is None:
        return ()
    translations = opus_provider.translate_variants(text, source_lang, target_lang)
    if not translations:
        return ()
    variants: list[TranslationVariant] = []
    for translation in translations:
        variants.append(
            TranslationVariant(
                ru=translation,
                pos=None,
                synonyms=(),
                examples=(),
                source=VariantSource.OPUS_MT,
            )
        )
    return tuple(variants)


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
    language_base: LanguageBase | None,
    text: str,
) -> TranslationVariant:
    if len(variant.examples) >= DEFAULT_MIN_EXAMPLES:
        return variant
    from_db: tuple[ExamplePair, ...] = ()
    if language_base is not None and language_base.is_available:
        from_db = language_base.get_examples(
            word=text,
            translation=variant.ru,
            limit=DEFAULT_MIN_EXAMPLES,
        )
        language_base_available = True
    else:
        language_base_available = False
    merged = _merge_examples(
        variant.examples,
        from_db,
        DEFAULT_MIN_EXAMPLES,
    )
    # Template examples exist only as a last resort when we don't have a local
    # language base yet. If the DB exists but has no matches, return fewer
    # examples instead of emitting unnatural templates.
    if len(merged) < DEFAULT_MIN_EXAMPLES and not language_base_available:
        merged = _merge_examples(
            merged,
            build_fallback_examples(text, variant.ru),
            DEFAULT_MIN_EXAMPLES,
        )
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
    language_base: LanguageBase | None,
) -> tuple[TranslationVariant, ...]:
    if not variants:
        return ()
    filled: list[TranslationVariant] = []
    for variant in variants:
        updated = await asyncio.to_thread(
            _fill_variant_examples,
            variant,
            language_base,
            text,
        )
        filled.append(updated)
    return tuple(filled)
