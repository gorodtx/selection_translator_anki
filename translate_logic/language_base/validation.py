from __future__ import annotations

import re
from typing import Final

MIN_EXAMPLE_WORDS: Final[int] = 4


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
    pattern = re.compile(rf"\b{re.escape(normalized_word)}(\b|['’])")
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
    # Allow basic inflection match for Russian words.
    if len(normalized_translation) < 5:
        return False
    for cut in (1, 2):
        stem = normalized_translation[:-cut]
        if len(stem) >= 4 and stem in normalized_ru:
            return True
    return False
