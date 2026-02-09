from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TypeAlias
from urllib.parse import quote_plus

from translate_logic.http import AsyncFetcher, FetchError
from translate_logic.text import normalize_whitespace
from translate_logic.translation import clean_translations

GOOGLE_TRANSLATE_BASE_URL = "https://translate.googleapis.com/translate_a/single"
GOOGLE_TRANSLATE_DT_PARAMS = (
    "bd",
    "ex",
    "ld",
    "md",
    "rw",
    "rm",
    "ss",
    "t",
    "at",
    "gt",
    "qca",
)

JsonValue: TypeAlias = (
    dict[str, "JsonValue"] | list["JsonValue"] | str | int | float | bool | None
)


@dataclass(frozen=True, slots=True)
class GoogleResult:
    translations: list[str]


def build_google_url(text: str, source_lang: str, target_lang: str) -> str:
    encoded = quote_plus(text)
    dt_params = "&".join(f"dt={param}" for param in GOOGLE_TRANSLATE_DT_PARAMS)
    params = (
        f"client=gtx&dj=1&ie=UTF-8&sl={source_lang}&tl={target_lang}"
        f"&{dt_params}&q={encoded}"
    )
    return f"{GOOGLE_TRANSLATE_BASE_URL}?{params}"


async def translate_google(
    text: str, source_lang: str, target_lang: str, fetcher: AsyncFetcher
) -> GoogleResult:
    if not text:
        return GoogleResult(translations=[])
    url = build_google_url(text, source_lang, target_lang)
    try:
        payload = await fetcher(url)
    except FetchError:
        return GoogleResult(translations=[])
    try:
        translations = parse_google_response(payload)
    except Exception:
        return GoogleResult(translations=[])
    return GoogleResult(translations=translations)


def parse_google_response(payload: str) -> list[str]:
    raw_payload: JsonValue = json.loads(payload)
    raw_data = _as_dict(raw_payload)
    if raw_data is None:
        return []
    translations = _extract_dict_terms(raw_data)
    translations.extend(_extract_alternative_translations(raw_data))
    translations.extend(_extract_sentence_translations(raw_data))
    return clean_translations(translations)


def _extract_sentence_translations(raw_data: dict[str, JsonValue]) -> list[str]:
    sentences = _as_list(raw_data.get("sentences"))
    if sentences is None:
        return []
    translations: list[str] = []
    for item in sentences:
        item_obj = _as_dict(item)
        if item_obj is None:
            continue
        trans_value = _get_str(item_obj.get("trans"))
        if trans_value:
            translations.append(trans_value)
    return translations


def _extract_dict_terms(raw_data: dict[str, JsonValue]) -> list[str]:
    dict_items = _as_list(raw_data.get("dict"))
    if dict_items is None:
        return []
    translations: list[str] = []
    for item in dict_items:
        item_obj = _as_dict(item)
        if item_obj is None:
            continue
        terms = _as_list(item_obj.get("terms"))
        if terms is None:
            continue
        for term in terms:
            term_value = _get_str(term)
            if term_value:
                translations.append(term_value)
    return translations


def _extract_alternative_translations(raw_data: dict[str, JsonValue]) -> list[str]:
    alt_items = _as_list(raw_data.get("alternative_translations"))
    if alt_items is None:
        return []
    translations: list[str] = []
    for item in alt_items:
        item_obj = _as_dict(item)
        if item_obj is None:
            continue
        alternatives = _as_list(item_obj.get("alternative_translations"))
        if alternatives is None:
            continue
        for alt in alternatives:
            alt_obj = _as_dict(alt)
            if alt_obj is None:
                continue
            for key in ("word_postproc", "word", "text"):
                value = _get_str(alt_obj.get(key))
                if value:
                    translations.append(value)
                    break
    return translations


def _as_dict(value: JsonValue) -> dict[str, JsonValue] | None:
    if isinstance(value, dict):
        return value
    return None


def _as_list(value: JsonValue) -> list[JsonValue] | None:
    if isinstance(value, list):
        return value
    return None


def _get_str(value: JsonValue) -> str | None:
    if isinstance(value, str):
        normalized = normalize_whitespace(value)
        return normalized or None
    return None
