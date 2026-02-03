from __future__ import annotations

from functools import lru_cache

from translate_logic.domain import rules

_CACHE_SIZE = 256


@lru_cache(maxsize=_CACHE_SIZE)
def _normalize_text_cached(value: str) -> str:
    return rules.normalize_text(value)


@lru_cache(maxsize=_CACHE_SIZE)
def _normalize_whitespace_cached(value: str) -> str:
    return rules.normalize_whitespace(value)


def normalize_text(value: str) -> str:
    return _normalize_text_cached(value)


def normalize_whitespace(value: str) -> str:
    return _normalize_whitespace_cached(value)
