from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import TypeGuard
from urllib.parse import quote

from translate_logic.http import AsyncFetcher, FetchError
from translate_logic.models import Example
from translate_logic.text import normalize_whitespace

DICTIONARY_API_BASE_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DictionaryApiResult:
    examples: list[Example]


def build_dictionary_api_url(text: str) -> str:
    return f"{DICTIONARY_API_BASE_URL}{quote(text)}"


async def translate_dictionary_api(
    text: str, fetcher: AsyncFetcher
) -> DictionaryApiResult:
    if not text:
        return DictionaryApiResult(examples=[])
    url = build_dictionary_api_url(text)
    try:
        payload = await fetcher(url)
<<<<<<< Updated upstream
    except FetchError as exc:
        logger.debug("Dictionary API fetch failed: %s", exc)
        return DictionaryApiResult(ipa_uk=None, examples=[])
    try:
        ipa_uk, examples = _parse_dictionary_api_payload(payload)
    except Exception as exc:
        logger.warning("Dictionary API parse failed: %s", exc)
        return DictionaryApiResult(ipa_uk=None, examples=[])
    return DictionaryApiResult(ipa_uk=ipa_uk, examples=examples)
=======
    except FetchError:
        return DictionaryApiResult(examples=[])
    try:
        examples = _parse_dictionary_api_payload(payload)
    except Exception:
        return DictionaryApiResult(examples=[])
    return DictionaryApiResult(examples=examples)
>>>>>>> Stashed changes


def _parse_dictionary_api_payload(payload: str) -> list[Example]:
    raw_data: object = json.loads(payload)
    entries = _coerce_dict_list(raw_data)
    examples: list[Example] = []
    example_texts: set[str] = set()
    for entry in entries:
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
    return examples


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
