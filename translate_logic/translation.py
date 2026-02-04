from __future__ import annotations

from translate_logic.models import TranslationLimit
from translate_logic.text import normalize_whitespace


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


def limit_translations(translations: list[str], limit: int | None = None) -> list[str]:
    effective_limit = limit or TranslationLimit.PRIMARY.value
    return translations[:effective_limit]
