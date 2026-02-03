from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
import logging
from typing import Final, Protocol

from reverso_context_api import Client as ReversoClient
from reverso_context_api import ReversoException

from translate_logic.models import (
    ExamplePair,
    ExampleSource,
    TranslationLimit,
    TranslationVariant,
    VariantSource,
)
from translate_logic.translation import clean_translations, limit_translations

logger = logging.getLogger(__name__)

REVERSO_MAX_EXAMPLES: Final[int] = 2
REVERSO_MAX_VARIANTS: Final[int] = TranslationLimit.PRIMARY.value
REVERSO_TIMEOUT_SECONDS: Final[float] = 3.0
REVERSO_RETRIES: Final[int] = 1


class ReversoClientProtocol(Protocol):
    def get_translations(
        self,
        text: str,
        source_lang: str | None = None,
        target_lang: str | None = None,
    ) -> Iterator[str]: ...

    def get_translation_samples(
        self,
        text: str,
        target_text: str | None = None,
        source_lang: str | None = None,
        target_lang: str | None = None,
        cleanup: bool = True,
    ) -> Iterator[tuple[str, str]]: ...


@dataclass(frozen=True, slots=True)
class ReversoResult:
    found: bool
    variants: tuple[TranslationVariant, ...]


async def translate_reverso(
    text: str,
    source_lang: str,
    target_lang: str,
    *,
    timeout_seconds: float = REVERSO_TIMEOUT_SECONDS,
    retries: int = REVERSO_RETRIES,
    max_variants: int = REVERSO_MAX_VARIANTS,
    max_examples: int = REVERSO_MAX_EXAMPLES,
    client: ReversoClientProtocol | None = None,
) -> ReversoResult:
    if not text.strip():
        return ReversoResult(found=False, variants=())
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    _translate_reverso_sync,
                    text,
                    source_lang,
                    target_lang,
                    max_variants,
                    max_examples,
                    client,
                ),
                timeout=timeout_seconds,
            )
        except (asyncio.TimeoutError, ReversoException) as exc:
            logger.warning("Reverso request failed (attempt %s): %s", attempt + 1, exc)
        except Exception:
            logger.exception("Reverso request failed (attempt %s)", attempt + 1)
    return ReversoResult(found=False, variants=())


def _translate_reverso_sync(
    text: str,
    source_lang: str,
    target_lang: str,
    max_variants: int,
    max_examples: int,
    client: ReversoClientProtocol | None,
) -> ReversoResult:
    if not text.strip():
        return ReversoResult(found=False, variants=())
    reverso_client = client or ReversoClient(source_lang, target_lang)
    translations = list(
        reverso_client.get_translations(
            text,
            source_lang=source_lang,
            target_lang=target_lang,
        )
    )
    cleaned = clean_translations(translations)
    limited = limit_translations(cleaned, max_variants)
    variants = tuple(
        _build_variant(
            reverso_client,
            text,
            translation,
            source_lang,
            target_lang,
            max_examples,
        )
        for translation in limited
    )
    return ReversoResult(found=bool(variants), variants=variants)


def _build_variant(
    client: ReversoClientProtocol,
    text: str,
    translation: str,
    source_lang: str,
    target_lang: str,
    max_examples: int,
) -> TranslationVariant:
    examples = _collect_examples(
        client, text, translation, source_lang, target_lang, max_examples
    )
    return TranslationVariant(
        ru=translation,
        pos=None,
        synonyms=(),
        examples=examples,
        source=VariantSource.REVERSO,
    )


def _collect_examples(
    client: ReversoClientProtocol,
    text: str,
    translation: str,
    source_lang: str,
    target_lang: str,
    max_examples: int,
) -> tuple[ExamplePair, ...]:
    items: list[ExamplePair] = []
    samples = client.get_translation_samples(
        text,
        target_text=translation,
        source_lang=source_lang,
        target_lang=target_lang,
        cleanup=True,
    )
    for source_text, translated_text in samples:
        normalized_source = source_text.strip()
        normalized_target = translated_text.strip()
        if not normalized_source or not normalized_target:
            continue
        items.append(
            ExamplePair(
                en=normalized_source,
                ru=normalized_target,
                source=ExampleSource.REVERSO,
            )
        )
        if len(items) >= max_examples:
            break
    return tuple(items)
