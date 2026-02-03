from __future__ import annotations

from translate_logic.domain.models import QueryLimit


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_text(value: str) -> str:
    collapsed = normalize_whitespace(value)
    if len(collapsed) > QueryLimit.MAX_CHARS.value:
        collapsed = collapsed[: QueryLimit.MAX_CHARS.value].rstrip()
    return collapsed
