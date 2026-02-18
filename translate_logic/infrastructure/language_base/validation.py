from __future__ import annotations

import re
from typing import Final

from translate_logic.infrastructure.language_base.morphology_ru import ru_lemma

MIN_EXAMPLE_WORDS: Final[int] = 4

_RU_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-zА-Яа-яЁё]+(?:[-'’][A-Za-zА-Яа-яЁё]+)?"
)


def word_count(value: str) -> int:
    return len([part for part in value.split() if part])


def normalize_spaces(value: str) -> str:
    return " ".join(value.split())


def contains_word(example: str, word: str) -> bool:
    """Check that example contains the exact word/phrase (case-insensitive)."""
    normalized_word = normalize_spaces(word).casefold()
    if not normalized_word:
        return False
    normalized_example = normalize_spaces(example).casefold()
    # Treat phrases and common punctuation as a substring match.
    if " " in normalized_word or "-" in normalized_word or "'" in normalized_word:
        return normalized_word in normalized_example
    # Single-word match with light morphology for English:
    # tables, table's, tabling, tabled, etc.
    base = re.escape(normalized_word)
    variants = [
        base,
        base + r"(?:s|es)",
        base + r"(?:['’]s)",
        base + r"(?:ed|ing)",
    ]
    if normalized_word.endswith("e") and len(normalized_word) > 1:
        no_e = re.escape(normalized_word[:-1])
        variants.append(no_e + r"(?:ed|ing)")
    pattern = re.compile(rf"\b(?:{'|'.join(variants)})\b")
    return bool(pattern.search(normalized_example))


def matches_translation(ru: str, translation: str) -> bool:
    """Best-effort check that RU side contains the requested translation.

    For multi-word translations require a substring match.
    For single words allow a simple inflectional match (stem containment).
    """
    normalized_translation = normalize_spaces(translation).casefold()
    if not normalized_translation:
        return False
    normalized_ru = normalize_spaces(ru).casefold()
    if (
        " " in normalized_translation
        or "-" in normalized_translation
        or "'" in normalized_translation
    ):
        return normalized_translation in normalized_ru
    if normalized_translation in normalized_ru:
        return True
    lemma = ru_lemma(normalized_translation)
    if lemma is None:
        return False
    for token in _RU_TOKEN_RE.findall(normalized_ru):
        if ru_lemma(token) == lemma:
            return True
    return False
