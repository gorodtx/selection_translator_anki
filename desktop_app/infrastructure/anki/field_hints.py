from __future__ import annotations

FIELD_HINTS: dict[str, list[str]] = {
    "word": ["word", "front", "expression", "term"],
    "translation": ["translation", "meaning", "ru"],
    "example_en": ["example", "sentence", "en"],
    "definitions_en": ["definition", "definitions", "gloss", "definition_en"],
}

REQUIRED_FIELD_KEYS = ("word", "translation", "example_en", "definitions_en")


def score_field_match(fields: list[str]) -> tuple[int, int]:
    lower_fields = [field.casefold() for field in fields]
    matched = 0
    for hints in FIELD_HINTS.values():
        if any(hint in field for field in lower_fields for hint in hints):
            matched += 1
    return matched, len(fields)
