from __future__ import annotations

from collections import Counter
import re
from typing import Final

from translate_logic.infrastructure.language_base.morphology_ru import ru_lemma

MIN_EXAMPLE_WORDS: Final[int] = 4
_EN_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
_REPEAT_TRIPLE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b([a-z0-9]+)\b(?:[\s,.;:!?\"'’()\-]+\1\b){2,}",
    re.IGNORECASE,
)
_PUNCT_HEAVY_RE: Final[re.Pattern[str]] = re.compile(r"[\"'“”«»()\\[\\]{}<>—–-]")

_RU_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-zА-Яа-яЁё]+(?:[-'’][A-Za-zА-Яа-яЁё]+)?"
)
_NORM_TRANSLATION_TABLE: Final[dict[int, str]] = str.maketrans(
    {
        ord("’"): "'",
        ord("‘"): "'",
        ord("`"): "'",
        ord("´"): "'",
        ord("“"): '"',
        ord("”"): '"',
        ord("«"): '"',
        ord("»"): '"',
        ord("—"): "-",
        ord("–"): "-",
        ord("‑"): "-",
        ord("_"): " ",
        ord("/"): " ",
        ord("\\"): " ",
    }
)
_NOISE_EDGE_RE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9' -]+")


def word_count(value: str) -> int:
    return len([part for part in value.split() if part])


def normalize_spaces(value: str) -> str:
    return " ".join(value.split())


def normalize_example_query(value: str) -> str:
    normalized = normalize_spaces(value).translate(_NORM_TRANSLATION_TABLE)
    normalized = _NOISE_EDGE_RE.sub(" ", normalized)
    tokens: list[str] = []
    for token in normalized.split():
        cleaned = token.strip("'-")
        if not cleaned:
            continue
        tokens.append(cleaned)
    return " ".join(tokens)


def is_noisy_example(example: str, query: str | None = None) -> bool:
    normalized = normalize_spaces(example)
    if not normalized:
        return True
    folded = normalized.casefold()
    if _REPEAT_TRIPLE_RE.search(folded):
        return True
    tokens = [token.casefold() for token in _EN_TOKEN_RE.findall(normalized)]
    if len(tokens) < 2:
        return True
    counts = Counter(tokens)
    unique_ratio = len(counts) / len(tokens)
    if len(tokens) >= 8 and unique_ratio < 0.56:
        return True
    max_freq = max(counts.values(), default=0)
    if len(tokens) >= 6 and max_freq / len(tokens) >= 0.30:
        return True
    if len(tokens) >= 8 and any(count >= 3 and len(token) >= 4 for token, count in counts.items()):
        return True
    bigrams = list(zip(tokens, tokens[1:], strict=False))
    if len(bigrams) >= 4:
        repeated = len(bigrams) - len(set(bigrams))
        if repeated / len(bigrams) >= 0.20:
            return True
        max_bigram_freq = max(Counter(bigrams).values(), default=0)
        if max_bigram_freq >= 2 and (max_bigram_freq / len(bigrams)) >= 0.18:
            return True
    query_tokens = []
    if query is not None:
        query_tokens = [
            token.casefold() for token in _EN_TOKEN_RE.findall(normalize_example_query(query))
        ]
    if query_tokens:
        for token in set(query_tokens):
            if len(token) >= 3 and counts.get(token, 0) >= 3:
                return True
    letters = sum(1 for char in normalized if char.isalpha())
    if letters > 0:
        punct_ratio = len(_PUNCT_HEAVY_RE.findall(normalized)) / letters
        if punct_ratio > 0.25:
            return True
    return False


def contains_word(example: str, word: str) -> bool:
    """Check that example contains the exact word/phrase (case-insensitive)."""
    normalized_word = normalize_example_query(word).casefold()
    if not normalized_word:
        return False
    normalized_example = normalize_example_query(example).casefold()
    word_tokens = [token.casefold() for token in _EN_TOKEN_RE.findall(normalized_word)]
    example_tokens = [
        token.casefold() for token in _EN_TOKEN_RE.findall(normalized_example)
    ]
    if not word_tokens or not example_tokens:
        return False
    if len(word_tokens) >= 2:
        if _contains_token_sequence(example_tokens, word_tokens):
            return True
        return normalized_word in normalized_example
    # Treat phrases and common punctuation as a substring match.
    token_word = word_tokens[0]
    # Single-word match with light morphology for English:
    # tables, table's, tabling, tabled, etc.
    base = re.escape(token_word)
    variants = [
        base,
        base + r"(?:s|es)",
        base + r"(?:['’]s)",
        base + r"(?:ed|ing)",
    ]
    if token_word.endswith("e") and len(token_word) > 1:
        no_e = re.escape(token_word[:-1])
        variants.append(no_e + r"(?:ed|ing)")
    pattern = re.compile(rf"\b(?:{'|'.join(variants)})\b")
    return bool(pattern.search(normalized_example))


def _contains_token_sequence(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(haystack) < len(needle):
        return False
    width = len(needle)
    for index in range(0, len(haystack) - width + 1):
        if haystack[index : index + width] == needle:
            return True
    return False


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
