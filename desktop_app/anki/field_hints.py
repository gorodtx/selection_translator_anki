from __future__ import annotations

FIELD_HINTS: dict[str, list[str]] = {
    "word": ["word", "front", "expression", "term"],
    "ipa": ["ipa", "phonetic", "pron"],
    "translation": ["translation", "meaning", "ru"],
    "example_en": ["example", "sentence", "en"],
    "example_ru": ["example_ru", "ru_example", "translation_example"],
}

REQUIRED_FIELD_KEYS = ("word", "ipa", "translation", "example_en", "example_ru")


def score_field_match(fields: list[str]) -> tuple[int, int]:
    lower_fields = [field.casefold() for field in fields]
    matched = 0
    for hints in FIELD_HINTS.values():
        if any(hint in field for field in lower_fields for hint in hints):
            matched += 1
    return matched, len(fields)
