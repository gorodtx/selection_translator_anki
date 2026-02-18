from __future__ import annotations

from translate_logic.domain import rules


def normalize_text(value: str) -> str:
    return rules.normalize_text(value)


def normalize_whitespace(value: str) -> str:
    return rules.normalize_whitespace(value)


def count_words(value: str) -> int:
    return rules.count_words(value)


def to_cambridge_slug(value: str) -> str:
    return rules.to_cambridge_slug(value)
