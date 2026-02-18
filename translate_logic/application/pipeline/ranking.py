from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from translate_logic.shared.text import count_words, normalize_whitespace
from translate_logic.shared.translation import is_meta_translation


class CandidateSource(Enum):
    CAMBRIDGE = "cambridge"
    GOOGLE = "google"


@dataclass(frozen=True, slots=True)
class RankedTranslation:
    text: str
    source: CandidateSource
    score: float
    signals: dict[str, float]


def rank_translation_candidates(
    query: str,
    *,
    cambridge: list[str],
    google: list[str],
    target_lang: str,
    limit: int,
) -> list[RankedTranslation]:
    normalized_query = normalize_whitespace(query)
    query_words = max(1, count_words(normalized_query))
    ranked: dict[str, RankedTranslation] = {}

    for source, values in (
        (CandidateSource.CAMBRIDGE, cambridge),
        (CandidateSource.GOOGLE, google),
    ):
        for raw in values:
            normalized = normalize_whitespace(raw)
            if not normalized:
                continue
            candidate = _score_candidate(
                query=normalized_query,
                query_words=query_words,
                text=normalized,
                source=source,
                target_lang=target_lang,
            )
            key = normalized.casefold()
            existing = ranked.get(key)
            if existing is None or candidate.score > existing.score:
                ranked[key] = candidate

    ordered = sorted(
        ranked.values(),
        key=lambda item: (
            item.score,
            item.source.value == CandidateSource.CAMBRIDGE.value,
        ),
        reverse=True,
    )
    return ordered[:limit]


def extract_ranked_texts(ranked: list[RankedTranslation]) -> list[str]:
    return [item.text for item in ranked]


def _score_candidate(
    *,
    query: str,
    query_words: int,
    text: str,
    source: CandidateSource,
    target_lang: str,
) -> RankedTranslation:
    signals: dict[str, float] = {}
    signals["source_weight"] = _source_weight(source=source, query_words=query_words)
    signals["length_penalty"] = _length_penalty(text)
    signals["meta_penalty"] = -2.0 if is_meta_translation(text) else 0.0
    signals["echo_penalty"] = -2.5 if text.casefold() == query.casefold() else 0.0
    signals["script_bonus"] = _script_bonus(text=text, target_lang=target_lang)
    signals["shape_bonus"] = _shape_bonus(text=text, query_words=query_words)
    score = sum(signals.values())
    return RankedTranslation(text=text, source=source, score=score, signals=signals)


def _source_weight(*, source: CandidateSource, query_words: int) -> float:
    if source is CandidateSource.CAMBRIDGE:
        return 2.5 if query_words <= 2 else 1.2
    return 2.4 if query_words >= 3 else 1.6


def _length_penalty(text: str) -> float:
    size = len(text)
    if size > 120:
        return -2.0
    if size > 80:
        return -1.3
    if size > 55:
        return -0.6
    if size < 2:
        return -1.0
    return 0.0


def _script_bonus(*, text: str, target_lang: str) -> float:
    target = target_lang.strip().lower()
    if not target.startswith("ru"):
        return 0.0
    has_cyrillic = any("а" <= char <= "я" or char == "ё" for char in text.casefold())
    return 1.0 if has_cyrillic else -0.8


def _shape_bonus(*, text: str, query_words: int) -> float:
    words = max(1, count_words(text))
    distance = abs(words - query_words)
    if distance == 0:
        return 0.6
    if distance == 1:
        return 0.2
    return -0.3
