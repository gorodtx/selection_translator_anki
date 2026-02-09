from __future__ import annotations

from urllib.parse import quote

from translate_logic.domain.models import ExampleLimit, QueryLimit


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_text(value: str) -> str:
    collapsed = normalize_whitespace(value)
    if len(collapsed) > QueryLimit.MAX_CHARS.value:
        collapsed = collapsed[: QueryLimit.MAX_CHARS.value].rstrip()
    return collapsed


def count_words(value: str) -> int:
    normalized = normalize_whitespace(value)
    if not normalized:
        return 0
    return len(normalized.split())


def to_cambridge_slug(value: str) -> str:
    normalized = normalize_text(value).lower()
    slug = normalized.replace(" ", "-")
    return quote(slug)


def is_example_candidate(text: str) -> bool:
    if not text:
        return False
    return count_words(text) >= ExampleLimit.MIN_WORDS.value
