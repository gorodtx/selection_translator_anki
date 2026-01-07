from __future__ import annotations

from enum import Enum

from translate_logic.models import TranslationLimit
from translate_logic.text import normalize_whitespace


class TranslationSeparator(Enum):
    DEFAULT = "; "


class TranslationThreshold(Enum):
    MAX_WORDS = 8
    MAX_CHARS = 80


class TranslationMetaMarker(Enum):
    FROM_VERB = "от гл."
    FROM_NOUN = "от сущ."
    FROM_ADJ = "от прил."
    FROM_ADV = "от нареч."
    PARTICIPLE = "прич."
    PAST_TENSE = "прош. вр."
    FORM = "форма"
    ABBR_RU = "аббр"
    ABBR_EN = "abbr"
    SHORT = "сокр."
    PAST_PARTICIPLE = "past participle"
    PLURAL_OF = "plural of"
    INDICATES = "указывает"
    MEANS = "означает"
    IN_COMBINATION = "в сочетании"
    TRANSMITTED = "передается"
    EXPRESSES = "выражает"
    DENOTES = "обозначает"


def clean_translations(translations: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in translations:
        normalized = normalize_whitespace(item)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def partition_translations(translations: list[str]) -> tuple[list[str], list[str]]:
    cleaned = clean_translations(translations)
    non_meta: list[str] = []
    meta: list[str] = []
    for item in cleaned:
        if is_meta_translation(item):
            meta.append(item)
        else:
            non_meta.append(item)
    return non_meta, meta


def merge_translations(primary: list[str], secondary: list[str]) -> list[str]:
    return clean_translations(primary + secondary)


def limit_translations(translations: list[str], limit: int | None = None) -> list[str]:
    effective_limit = limit or TranslationLimit.PRIMARY.value
    return translations[:effective_limit]


def combine_translations(
    translations: list[str], limit: int | None = None
) -> str | None:
    cleaned = clean_translations(translations)
    limited = limit_translations(cleaned, limit)
    if not limited:
        return None
    return TranslationSeparator.DEFAULT.value.join(limited)


def combine_translation_variants(
    primary: list[str], secondary: list[str], limit: int | None = None
) -> str | None:
    merged = merge_translations(primary, secondary)
    return combine_translations(merged, limit)


def select_translation_candidates(translations: list[str]) -> list[str]:
    non_meta, meta = partition_translations(translations)
    return non_meta if non_meta else meta


def select_primary_translation(translations: list[str]) -> str | None:
    non_meta, meta = partition_translations(translations)
    preferred = non_meta if non_meta else meta
    if not preferred:
        return None
    return preferred[0]


def is_meta_translation(value: str) -> bool:
    normalized = normalize_whitespace(value)
    if _exceeds_thresholds(normalized):
        return True
    lowered = normalized.casefold()
    return any(marker.value in lowered for marker in TranslationMetaMarker)


def _exceeds_thresholds(value: str) -> bool:
    word_count = len(value.split())
    if word_count > TranslationThreshold.MAX_WORDS.value:
        return True
    return len(value) > TranslationThreshold.MAX_CHARS.value
