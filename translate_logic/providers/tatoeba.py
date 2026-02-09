from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import TypeGuard
from urllib.parse import quote_plus

from translate_logic.http import AsyncFetcher, FetchError
from translate_logic.models import Example
from translate_logic.text import normalize_text, normalize_whitespace

TATOEBA_BASE_URL = "https://api.tatoeba.org/unstable/sentences"
TATOEBA_DEFAULT_LIMIT = 5


class TatoebaLanguage(Enum):
    ENGLISH = "eng"
    RUSSIAN = "rus"


class TatoebaSort(Enum):
    RELEVANCE = "relevance"


class TatoebaFlag(Enum):
    YES = "yes"


@dataclass(frozen=True, slots=True)
class TatoebaResult:
    examples: list[Example]


def build_tatoeba_url(text: str) -> str:
    normalized = normalize_text(text)
    encoded = quote_plus(normalized)
    params = (
        f"lang={TatoebaLanguage.ENGLISH.value}",
        f"q={encoded}",
        f"trans:lang={TatoebaLanguage.RUSSIAN.value}",
        f"showtrans:lang={TatoebaLanguage.RUSSIAN.value}",
        f"showtrans:is_direct={TatoebaFlag.YES.value}",
        f"sort={TatoebaSort.RELEVANCE.value}",
        f"limit={TATOEBA_DEFAULT_LIMIT}",
    )
    return f"{TATOEBA_BASE_URL}?{'&'.join(params)}"


async def translate_tatoeba(text: str, fetcher: AsyncFetcher) -> TatoebaResult:
    if not text:
        return TatoebaResult(examples=[])
    url = build_tatoeba_url(text)
    try:
        payload = await fetcher(url)
    except FetchError:
        return TatoebaResult(examples=[])
    try:
        examples = _parse_tatoeba_payload(payload)
    except Exception:
        return TatoebaResult(examples=[])
    return TatoebaResult(examples=examples)


def _parse_tatoeba_payload(payload: str) -> list[Example]:
    raw_data: object = json.loads(payload)
    raw_dict = _coerce_dict(raw_data)
    if raw_dict is None:
        return []
    data_obj: object = raw_dict.get("data")
    data_list = _coerce_list(data_obj)
    if data_list is None:
        return []

    examples: list[Example] = []
    seen: set[tuple[str, str | None]] = set()
    for item in data_list:
        item_dict = _coerce_dict(item)
        if item_dict is None:
            continue
        lang = _get_str(item_dict.get("lang"))
        if lang != TatoebaLanguage.ENGLISH.value:
            continue
        en_text = _get_str(item_dict.get("text"))
        if en_text is None:
            continue
        translations = _coerce_dict_list(item_dict.get("translations"))
        for translation in translations:
            ru_text = _get_str(translation.get("text"))
            ru_lang = _get_str(translation.get("lang"))
            if ru_text is None or ru_lang != TatoebaLanguage.RUSSIAN.value:
                continue
            is_direct = _get_bool(translation.get("is_direct"))
            if is_direct is False:
                continue
            example = Example(
                en=normalize_whitespace(en_text),
                ru=normalize_whitespace(ru_text),
            )
            key = (example.en, example.ru)
            if key not in seen:
                examples.append(example)
                seen.add(key)
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


def _coerce_list(value: object) -> list[object] | None:
    if not _is_object_list(value):
        return None
    return list(value)


def _coerce_dict(value: object) -> dict[str, object] | None:
    if not _is_str_dict(value):
        return None
    return dict(value)


def _get_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _get_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)
