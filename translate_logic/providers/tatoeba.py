from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import logging
from urllib.parse import quote_plus

from translate_logic.http import AsyncFetcher, FetchError
from translate_logic.models import Example
from translate_logic.text import normalize_text, normalize_whitespace

TATOEBA_BASE_URL = "https://api.tatoeba.org/unstable/sentences"
TATOEBA_DEFAULT_LIMIT = 5

logger = logging.getLogger(__name__)


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
    except FetchError as exc:
        logger.debug("Tatoeba fetch failed: %s", exc)
        return TatoebaResult(examples=[])
    try:
        examples = _parse_tatoeba_payload(payload)
    except Exception as exc:
        logger.warning("Tatoeba parse failed: %s", exc)
        return TatoebaResult(examples=[])
    return TatoebaResult(examples=examples)


def _parse_tatoeba_payload(payload: str) -> list[Example]:
    raw_data: object = json.loads(payload)
    if not isinstance(raw_data, dict):
        return []
    data_obj: object = raw_data.get("data")
    if not isinstance(data_obj, list):
        return []

    examples: list[Example] = []
    seen: set[tuple[str, str | None]] = set()
    for item in data_obj:
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
    if not isinstance(value, list):
        return []
    results: list[dict[str, object]] = []
    for item in value:
        item_dict = _coerce_dict(item)
        if item_dict is not None:
            results.append(item_dict)
    return results


def _coerce_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    output: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        output[key] = item
    return output


def _get_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _get_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None
