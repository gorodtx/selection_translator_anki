from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from urllib.parse import quote_plus

from translate_logic.html_parser import (
    HtmlNode,
    find_all,
    find_first,
    has_ancestor_with_class,
    parse_html,
)
from translate_logic.http import AsyncFetcher, FetchError
from translate_logic.models import Example
from translate_logic.text import normalize_text, normalize_whitespace, to_cambridge_slug
from translate_logic.translation import clean_translations

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
    ipa_uk: str | None
    translations: list[str]
    examples: list[Example]


@dataclass(frozen=True, slots=True)
class CambridgeResult:
    found: bool
    translations: list[str]
    ipa_uk: str | None
    examples: list[Example]


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
            ipa_uk=None,
            examples=[],
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
        ipa_uk = english_data.ipa_uk or russian_data.ipa_uk
        examples = _rank_examples(russian_data.examples or english_data.examples)

        result = CambridgeResult(
            found=bool(translations),
            translations=translations,
            ipa_uk=ipa_uk,
            examples=examples,
        )
        if result.found:
            return result
        if best_fallback is None and (ipa_uk or examples):
            best_fallback = result

    if best_fallback is not None:
        return best_fallback
    return CambridgeResult(
        found=False,
        translations=[],
        ipa_uk=None,
        examples=[],
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
    ipa_uk: str | None = None
    translations: list[str] = []
    examples: list[Example] = []
    seen_examples: set[tuple[str, str | None]] = set()

    for entry in entries:
        if ipa_uk is None:
            ipa_uk = _extract_ipa_uk(entry)
        for translation in _extract_entry_translations(entry, translation_lang):
            translations.append(translation)
        for example in _extract_entry_examples(entry):
            key = (example.en, example.ru)
            if key not in seen_examples:
                examples.append(example)
                seen_examples.add(key)

    if not entries:
        ipa_uk = _extract_ipa_uk(root)
        translations = _extract_translations(root, translation_lang)
        examples = _extract_examples(root)
    translations = clean_translations(translations)
    return CambridgePageData(
        ipa_uk=ipa_uk,
        translations=translations,
        examples=examples,
    )


def _empty_page_data() -> CambridgePageData:
    return CambridgePageData(
        ipa_uk=None,
        translations=[],
        examples=[],
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


def _extract_ipa_uk(root: HtmlNode) -> str | None:
    def _is_pron(node: HtmlNode) -> bool:
        return node.tag == "span" and {"pron", "dpron"}.issubset(node.classes())

    def _is_ipa(node: HtmlNode) -> bool:
        return node.tag == "span" and {"ipa", "dipa"}.issubset(node.classes())

    def _is_uk_pron(node: HtmlNode) -> bool:
        return _is_pron(node) and has_ancestor_with_class(node, "uk")

    def _is_uk_ipa(node: HtmlNode) -> bool:
        return _is_ipa(node) and has_ancestor_with_class(node, "uk")

    predicates: list[Callable[[HtmlNode], bool]] = [
        _is_uk_pron,
        _is_pron,
        _is_uk_ipa,
        _is_ipa,
    ]
    for predicate in predicates:
        node = find_first(root, predicate)
        if node is None:
            continue
        text = normalize_whitespace(node.text_content())
        if text:
            return text
    return None


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
    seen: set[tuple[str, str | None]] = set()
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
        ru_text = _extract_example_text(node, "trans")
        example = Example(en=en_text, ru=ru_text)
        key = (example.en, example.ru)
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
        ru_text = _extract_example_text(node, "trans")
        examples.append(Example(en=en_text, ru=ru_text))
    return _rank_examples(examples)


def _rank_examples(examples: list[Example]) -> list[Example]:
    indexed = list(enumerate(examples))
    indexed.sort(key=lambda item: (-_example_score(item[1]), item[0]))
    return [example for _, example in indexed]


def _example_score(example: Example) -> int:
    score = 0
    if example.ru:
        score += 4
    length = len(example.en)
    if 20 <= length <= 120:
        score += 2
    elif length < 10:
        score -= 1
    elif length > 160:
        score -= 2
    if "..." in example.en or "…" in example.en:
        score -= 1
    return score


def _normalize_lang(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None
