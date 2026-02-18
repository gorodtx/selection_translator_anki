from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import time
from urllib.parse import quote_plus

from translate_logic.shared.example_selection import rank_diverse_examples
from translate_logic.infrastructure.http.html_parser import (
    HtmlNode,
    find_all,
    has_ancestor_with_class,
    parse_html,
)
from translate_logic.infrastructure.http.transport import AsyncFetcher, FetchError
from translate_logic.models import Example
from translate_logic.shared.text import normalize_text, normalize_whitespace, to_cambridge_slug
from translate_logic.shared.translation import clean_translations

CAMBRIDGE_BASE_URL = "https://dictionary.cambridge.org"
CAMBRIDGE_SEARCH_URL = f"{CAMBRIDGE_BASE_URL}/search/direct/"
CAMBRIDGE_RUSSIAN_LANG = "ru"


class CambridgeDataset(Enum):
    ENGLISH = "english"
    ENGLISH_RUSSIAN = "english-russian"


@dataclass(frozen=True, slots=True)
class CambridgeUrls:
    english: str
    english_russian: str


@dataclass(frozen=True, slots=True)
class CambridgePageData:
    translations: list[str]
    examples: list[Example]
    definitions_en: list[str]


@dataclass(frozen=True, slots=True)
class CambridgeResult:
    found: bool
    translations: list[str]
    examples: list[Example]
    definitions_en: list[str]


def build_cambridge_urls(query: str) -> CambridgeUrls:
    return CambridgeUrls(
        english=_build_cambridge_search_url(CambridgeDataset.ENGLISH, query),
        english_russian=_build_cambridge_search_url(
            CambridgeDataset.ENGLISH_RUSSIAN, query
        ),
    )


async def translate_cambridge(text: str, fetcher: AsyncFetcher) -> CambridgeResult:
    queries = _build_cambridge_queries(text)
    if not queries:
        return CambridgeResult(
            found=False,
            translations=[],
            examples=[],
            definitions_en=[],
        )

    best_fallback: CambridgeResult | None = None
    for query in queries:
        urls = build_cambridge_urls(query)
        english_html, russian_html = await asyncio.gather(
            _try_fetch(fetcher, urls.english),
            _try_fetch(fetcher, urls.english_russian),
        )

        if english_html is None and russian_html is None:
            continue

        try:
            english_data = (
                parse_cambridge_page(english_html)
                if english_html is not None
                else _empty_page_data()
            )
            russian_data = (
                parse_cambridge_page(
                    russian_html, translation_lang=CAMBRIDGE_RUSSIAN_LANG
                )
                if russian_html is not None
                else _empty_page_data()
            )
        except Exception:
            continue

        translations = russian_data.translations or english_data.translations
        examples = _rank_examples(russian_data.examples or english_data.examples)
        definitions_en = english_data.definitions_en or russian_data.definitions_en

        result = CambridgeResult(
            found=bool(translations),
            translations=translations,
            examples=examples,
            definitions_en=definitions_en,
        )
        if result.found:
            return result
        if best_fallback is None and (examples or definitions_en):
            best_fallback = result

    if best_fallback is not None:
        return best_fallback
    return CambridgeResult(
        found=False,
        translations=[],
        examples=[],
        definitions_en=[],
    )


async def _try_fetch(fetcher: AsyncFetcher, url: str) -> str | None:
    try:
        return await fetcher(url)
    except FetchError:
        return None


def parse_cambridge_page(
    html: str, translation_lang: str | None = None
) -> CambridgePageData:
    root = parse_html(html)
    entries = find_all(root, _is_entry_block)
    translations: list[str] = []
    examples: list[Example] = []
    seen_examples: set[str] = set()

    for entry in entries:
        for translation in _extract_entry_translations(entry, translation_lang):
            translations.append(translation)
        for example in _extract_entry_examples(entry):
            key = example.en.casefold()
            if key not in seen_examples:
                examples.append(example)
                seen_examples.add(key)

    if not entries:
        translations = _extract_translations(root, translation_lang)
        examples = _extract_examples(root)
    translations = clean_translations(translations)
    return CambridgePageData(
        translations=translations,
        examples=examples,
        definitions_en=_extract_definitions(root),
    )


def _empty_page_data() -> CambridgePageData:
    return CambridgePageData(
        translations=[],
        examples=[],
        definitions_en=[],
    )


def _is_entry_block(node: HtmlNode) -> bool:
    classes = node.classes()
    if not classes:
        return False
    return (
        "entry-body__el" in classes
        or "pv-block" in classes
        or ("pr" in classes and "dictionary" in classes)
        or ("pr" in classes and "idiom-block" in classes)
    )


def _is_def_block(node: HtmlNode) -> bool:
    return node.tag == "div" and "def-block" in node.classes()


def _is_def_body(node: HtmlNode) -> bool:
    return node.tag == "div" and "def-body" in node.classes()


def _build_cambridge_queries(value: str) -> list[str]:
    normalized = normalize_text(value)
    if not normalized:
        return []
    primary = quote_plus(normalized)
    slug = to_cambridge_slug(value)
    queries = [primary]
    if slug and slug not in queries:
        queries.append(slug)
    return queries


def _build_cambridge_search_url(dataset: CambridgeDataset, query: str) -> str:
    return f"{CAMBRIDGE_SEARCH_URL}?datasetsearch={dataset.value}&q={query}"


def _extract_translations(
    root: HtmlNode, translation_lang: str | None = None
) -> list[str]:
    translations: list[str] = []
    nodes = find_all(
        root,
        lambda node: node.tag == "span" and "trans" in node.classes(),
    )
    for node in nodes:
        if has_ancestor_with_class(node, "examp") or has_ancestor_with_class(
            node, "dexamp"
        ):
            continue
        lang = _normalize_lang(node.attrs.get("lang"))
        if (
            translation_lang
            and lang is not None
            and not lang.startswith(translation_lang)
        ):
            continue
        text = normalize_whitespace(node.text_content())
        if text and text not in translations:
            translations.append(text)
    return translations


def _extract_examples(root: HtmlNode) -> list[Example]:
    examples: list[Example] = []
    seen: set[str] = set()
    nodes = find_all(
        root,
        lambda node: node.tag == "div" and "examp" in node.classes(),
    )
    for node in nodes:
        en_text = _build_example_english(node)
        if not en_text:
            en_text = normalize_whitespace(node.text_content())
        if not en_text:
            continue
        example = Example(en=en_text)
        key = example.en.casefold()
        if key in seen:
            continue
        seen.add(key)
        examples.append(example)
    return _rank_examples(examples)


def _extract_example_text(node: HtmlNode, class_name: str) -> str | None:
    matches = find_all(
        node, lambda target: target.tag == "span" and class_name in target.classes()
    )
    for match in matches:
        text = normalize_whitespace(match.text_content())
        if text:
            return text
    return None


def _build_example_english(node: HtmlNode) -> str | None:
    sentence = _extract_example_text(node, "eg")
    if sentence:
        return sentence
    lead_in = _extract_example_text(node, "lu")
    if lead_in:
        return lead_in
    return None


def _extract_entry_translations(
    entry: HtmlNode, translation_lang: str | None
) -> list[str]:
    def_blocks = find_all(entry, _is_def_block)
    if not def_blocks:
        return _extract_translations(entry, translation_lang)
    translations: list[str] = []
    for def_block in def_blocks:
        def_bodies = find_all(def_block, _is_def_body)
        if not def_bodies:
            def_bodies = [def_block]
        for def_body in def_bodies:
            translations.extend(_extract_translations(def_body, translation_lang))
    return translations


def _extract_entry_examples(entry: HtmlNode) -> list[Example]:
    def_blocks = find_all(entry, _is_def_block)
    nodes: list[HtmlNode] = []
    if def_blocks:
        for def_block in def_blocks:
            nodes.extend(
                find_all(
                    def_block,
                    lambda node: node.tag == "div" and "examp" in node.classes(),
                )
            )
    if not nodes:
        nodes = find_all(
            entry,
            lambda node: node.tag == "div" and "examp" in node.classes(),
        )
    examples: list[Example] = []
    for node in nodes:
        en_text = _build_example_english(node)
        if not en_text:
            en_text = normalize_whitespace(node.text_content())
        if not en_text:
            continue
        examples.append(Example(en=en_text))
    return _rank_examples(examples)


def _extract_definitions(root: HtmlNode, limit: int = 8) -> list[str]:
    definitions: list[str] = []
    seen: set[str] = set()
    nodes = find_all(root, _is_definition_text_node)
    for node in nodes:
        if has_ancestor_with_class(node, "examp") or has_ancestor_with_class(
            node, "dexamp"
        ):
            continue
        text = normalize_whitespace(node.text_content())
        if not text or not _looks_like_definition(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        definitions.append(text)
        if len(definitions) >= limit:
            break
    return definitions


def _is_definition_text_node(node: HtmlNode) -> bool:
    if node.tag not in {"span", "div"}:
        return False
    classes = node.classes()
    if "def" in classes and ("ddef_d" in classes or "ddef_b" in classes):
        return True
    if "def-body__text" in classes:
        return True
    return False


def _looks_like_definition(text: str) -> bool:
    if len(text) < 8:
        return False
    if text.endswith(":"):
        return False
    has_latin = any("a" <= char <= "z" for char in text.casefold())
    return has_latin


def _rank_examples(examples: list[Example]) -> list[Example]:
    return rank_diverse_examples(
        examples,
        seed=f"cambridge:{time.time_ns()}",
    )


def _normalize_lang(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None
