from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Final

from translate_logic.models import (
    ExamplePair,
    TranslationResult,
    TranslationVariant,
)
from translate_logic.language_base.base import LanguageBase
from translate_logic.providers.opus_mt import OpusMtProvider
from translate_logic.text import normalize_text

DEFAULT_MIN_EXAMPLES: Final[int] = 3
DEFAULT_VARIANTS: Final[int] = 7


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
    shared_examples = await _fetch_examples_async(
        normalized_text,
        language_base,
    )
    return TranslationResult(
        variants=_attach_shared_examples(variants, shared_examples)
    )


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


def _attach_shared_examples(
    variants: tuple[TranslationVariant, ...],
    examples: tuple[ExamplePair, ...],
) -> tuple[TranslationVariant, ...]:
    """Attach examples as a shared pool for the whole request.

    We intentionally do NOT try to pick different examples per RU variant.
    """
    if not variants or not examples:
        return variants
    first = variants[0]
    updated_first = TranslationVariant(
        ru=first.ru,
        pos=first.pos,
        synonyms=first.synonyms,
        examples=examples,
    )
    return (updated_first,) + variants[1:]


async def _fetch_examples_async(
    text: str,
    language_base: LanguageBase | None,
) -> tuple[ExamplePair, ...]:
    if language_base is None or not language_base.is_available:
        return ()
    return await asyncio.to_thread(
        language_base.get_examples,
        word=text,
        limit=DEFAULT_MIN_EXAMPLES,
    )
