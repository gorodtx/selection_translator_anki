from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TypeGuard
from urllib.parse import quote

from translate_logic.http import AsyncFetcher, FetchError
from translate_logic.models import Example
from translate_logic.text import normalize_whitespace

DICTIONARY_API_BASE_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"


@dataclass(frozen=True, slots=True)
class DictionaryApiResult:
    ipa_uk: str | None
    examples: list[Example]


def build_dictionary_api_url(text: str) -> str:
    return f"{DICTIONARY_API_BASE_URL}{quote(text)}"


async def translate_dictionary_api(
    text: str, fetcher: AsyncFetcher
) -> DictionaryApiResult:
    if not text:
        return DictionaryApiResult(ipa_uk=None, examples=[])
    url = build_dictionary_api_url(text)
    try:
        payload = await fetcher(url)
    except FetchError:
        return DictionaryApiResult(ipa_uk=None, examples=[])
    try:
        ipa_uk, examples = _parse_dictionary_api_payload(payload)
    except Exception:
        return DictionaryApiResult(ipa_uk=None, examples=[])
    return DictionaryApiResult(ipa_uk=ipa_uk, examples=examples)


def _parse_dictionary_api_payload(
    payload: str,
) -> tuple[str | None, list[Example]]:
    raw_data: object = json.loads(payload)
    entries = _coerce_dict_list(raw_data)
    phonetics: list[dict[str, object]] = []
    examples: list[Example] = []
    example_texts: set[str] = set()
    for entry in entries:
        phonetics.extend(_coerce_dict_list(entry.get("phonetics")))
        meanings = _coerce_dict_list(entry.get("meanings"))
        for meaning in meanings:
            definitions = _coerce_dict_list(meaning.get("definitions"))
            for definition in definitions:
                example = _get_str(definition.get("example"))
                if example is None:
                    continue
                normalized = normalize_whitespace(example)
                if normalized and normalized not in example_texts:
                    examples.append(Example(en=normalized, ru=None))
                    example_texts.add(normalized)
    ipa_uk = _select_phonetics(phonetics)
    return ipa_uk, examples


def _select_phonetics(phonetics: list[dict[str, object]]) -> str | None:
    candidates: list[str] = []
    for entry in phonetics:
        text = _get_str(entry.get("text"))
        if text:
            candidates.append(text)
    if not candidates:
        return None
    for text in candidates:
        if "əʊ" in text or "ɒ" in text:
            return text
    return candidates[0]


def _coerce_dict_list(value: object) -> list[dict[str, object]]:
    if not _is_object_list(value):
        return []
    results: list[dict[str, object]] = []
    for item in value:
        item_dict = _coerce_dict(item)
        if item_dict is not None:
            results.append(item_dict)
    return results


def _coerce_dict(value: object) -> dict[str, object] | None:
    if not _is_str_dict(value):
        return None
    return dict(value)


def _get_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)
