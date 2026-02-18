from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
import math
import re
import time
from typing import Final

from translate_logic.models import Example
from translate_logic.shared.text import normalize_whitespace

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_PUNCT_RE = re.compile(r"[\"'“”«»()\\[\\]{}<>—–-]")
_HIGH_AMBIGUITY_TOKENS: Final[set[str]] = {"a", "i", "x"}
_MMR_LAMBDA: Final[float] = 0.35
_NOVELTY_MU: Final[float] = 0.25
_JITTER_MAX: Final[float] = 0.03
_RECENT_RING_SIZE: Final[int] = 12
_RECENT_KEYS_LIMIT: Final[int] = 512
_RECENT_TTL_S: Final[float] = 1800.0
_LATENCY_SAMPLES: Final[int] = 256


@dataclass(frozen=True, slots=True)
class _Candidate:
    example: Example
    signature: str
    token_set: frozenset[str]
    prefix_tokens: tuple[str, ...]
    relevance: float


@dataclass(frozen=True, slots=True)
class SelectorStats:
    total_calls: int
    budget_fallback_calls: int
    novelty_hits: int
    avg_candidate_n: float
    avg_selection_ms: float
    p95_selection_ms: float


@dataclass(slots=True)
class NoveltyState:
    ring_size: int = _RECENT_RING_SIZE
    max_keys: int = _RECENT_KEYS_LIMIT
    ttl_s: float = _RECENT_TTL_S
    _recent: dict[str, deque[str]] = field(default_factory=dict, init=False, repr=False)
    _last_seen: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def penalty(self, query_key: str, signature: str) -> float:
        if not query_key:
            return 0.0
        self._cleanup()
        recent = self._recent.get(query_key)
        if not recent:
            return 0.0
        self._last_seen[query_key] = time.monotonic()
        items = list(recent)
        for reverse_index, value in enumerate(reversed(items)):
            if value != signature:
                continue
            if len(items) <= 1:
                freshness = 1.0
            else:
                freshness = 1.0 - (reverse_index / (len(items) - 1))
            return 0.15 + (0.20 * freshness)
        return 0.0

    def remember(self, query_key: str, signatures: list[str]) -> None:
        if not query_key or not signatures:
            return
        self._cleanup()
        recent = self._recent.get(query_key)
        if recent is None:
            recent = deque(maxlen=self.ring_size)
            self._recent[query_key] = recent
        for signature in signatures:
            try:
                recent.remove(signature)
            except ValueError:
                pass
            recent.append(signature)
        self._last_seen[query_key] = time.monotonic()
        self._trim_to_budget()

    def _cleanup(self) -> None:
        now = time.monotonic()
        stale = [
            key
            for key, last_seen in self._last_seen.items()
            if now - last_seen > self.ttl_s
        ]
        for key in stale:
            self._last_seen.pop(key, None)
            self._recent.pop(key, None)

    def _trim_to_budget(self) -> None:
        while len(self._recent) > self.max_keys:
            oldest_key = min(self._last_seen, key=lambda key: self._last_seen[key])
            self._last_seen.pop(oldest_key, None)
            self._recent.pop(oldest_key, None)


@dataclass(slots=True)
class _SelectorStatsTracker:
    total_calls: int = 0
    budget_fallback_calls: int = 0
    novelty_hits: int = 0
    candidate_sum: int = 0
    selection_ms_sum: float = 0.0
    latency_samples: deque[float] = field(
        default_factory=lambda: deque(maxlen=_LATENCY_SAMPLES)
    )

    def record(
        self,
        *,
        candidate_n: int,
        selection_ms: float,
        budget_fallback: bool,
        novelty_hits: int,
    ) -> None:
        self.total_calls += 1
        if budget_fallback:
            self.budget_fallback_calls += 1
        self.novelty_hits += novelty_hits
        self.candidate_sum += candidate_n
        self.selection_ms_sum += selection_ms
        self.latency_samples.append(selection_ms)

    def snapshot(self) -> SelectorStats:
        calls = self.total_calls or 1
        samples = sorted(self.latency_samples)
        if not samples:
            p95 = 0.0
        else:
            index = max(0, math.ceil(len(samples) * 0.95) - 1)
            p95 = samples[index]
        return SelectorStats(
            total_calls=self.total_calls,
            budget_fallback_calls=self.budget_fallback_calls,
            novelty_hits=self.novelty_hits,
            avg_candidate_n=self.candidate_sum / calls,
            avg_selection_ms=self.selection_ms_sum / calls,
            p95_selection_ms=p95,
        )


_STATS = _SelectorStatsTracker()


def rank_diverse_examples(
    examples: list[Example],
    *,
    seed: str | None = None,
) -> list[Example]:
    return select_examples_v3(
        examples,
        query="",
        limit=max(0, len(examples)),
        seed_key=seed,
        novelty_state=None,
        candidate_cap=max(40, len(examples)),
        latency_budget_ms=20.0,
    )


def select_diverse_examples(
    examples: list[Example],
    *,
    limit: int,
    seed: str | None = None,
) -> list[Example]:
    return select_examples_v3(
        examples,
        query="",
        limit=limit,
        seed_key=seed,
        novelty_state=None,
        candidate_cap=max(40, min(80, len(examples))),
        latency_budget_ms=20.0,
    )


def select_examples_v3(
    examples: list[Example],
    *,
    query: str,
    limit: int,
    bm25_scores: list[float] | None = None,
    candidate_cap: int = 64,
    latency_budget_ms: float = 20.0,
    seed_bucket_s: int = 600,
    seed_key: str | None = None,
    novelty_state: NoveltyState | None = None,
) -> list[Example]:
    started = time.perf_counter()
    if limit <= 0 or not examples:
        return []

    query_key = normalize_whitespace(query).casefold()
    query_tokens = tuple(dict.fromkeys(_tokens(query_key)))
    query_token_set = frozenset(query_tokens)
    selected_limit = max(1, limit)
    bounded_cap = max(selected_limit, min(candidate_cap, len(examples)))
    candidates = _build_candidates(
        examples=examples,
        bm25_scores=bm25_scores,
        query_key=query_key,
        query_token_set=query_token_set,
        candidate_cap=bounded_cap,
    )
    if not candidates:
        _STATS.record(
            candidate_n=0,
            selection_ms=_elapsed_ms(started),
            budget_fallback=False,
            novelty_hits=0,
        )
        return []

    bucket = int(time.time() // max(1, seed_bucket_s))
    seed_base = seed_key or query_key or "selector"
    remaining = list(candidates)
    selected: list[_Candidate] = []
    novelty_hits = 0
    budget_fallback = False

    while remaining and len(selected) < selected_limit:
        if _elapsed_ms(started) > latency_budget_ms:
            budget_fallback = True
            break
        best_index = 0
        best_score = -1_000_000.0
        best_novelty = 0.0
        for index, candidate in enumerate(remaining):
            similarity_penalty = 0.0
            if selected:
                similarity_penalty = max(
                    _candidate_similarity(candidate, item) for item in selected
                )
            novelty_penalty = (
                novelty_state.penalty(query_key, candidate.signature)
                if novelty_state is not None
                else 0.0
            )
            jitter = _deterministic_jitter(
                seed=seed_base,
                signature=candidate.signature,
                bucket=bucket,
            )
            score = (
                candidate.relevance
                - (_MMR_LAMBDA * similarity_penalty)
                - (_NOVELTY_MU * novelty_penalty)
                + jitter
            )
            if score > best_score:
                best_score = score
                best_index = index
                best_novelty = novelty_penalty
        picked = remaining.pop(best_index)
        selected.append(picked)
        if best_novelty > 0:
            novelty_hits += 1

    if len(selected) < selected_limit and remaining:
        budget_fallback = True
        remaining.sort(
            key=lambda item: (
                item.relevance
                + _deterministic_jitter(
                    seed=seed_base,
                    signature=item.signature,
                    bucket=bucket,
                )
            ),
            reverse=True,
        )
        for candidate in remaining:
            selected.append(candidate)
            if len(selected) >= selected_limit:
                break

    chosen = selected[:selected_limit]
    if novelty_state is not None and query_key:
        novelty_state.remember(
            query_key,
            [item.signature for item in chosen],
        )

    _STATS.record(
        candidate_n=len(candidates),
        selection_ms=_elapsed_ms(started),
        budget_fallback=budget_fallback,
        novelty_hits=novelty_hits,
    )
    return [item.example for item in chosen]


def selector_stats_snapshot() -> SelectorStats:
    return _STATS.snapshot()


def _build_candidates(
    *,
    examples: list[Example],
    bm25_scores: list[float] | None,
    query_key: str,
    query_token_set: frozenset[str],
    candidate_cap: int,
) -> list[_Candidate]:
    raw: list[
        tuple[Example, str, frozenset[str], tuple[str, ...], float, float, float, float]
    ] = []
    seen_signatures: set[str] = set()

    for index, source in enumerate(examples):
        text = normalize_whitespace(source.en)
        if not text:
            continue
        text_tokens = _tokens(text)
        if len(text_tokens) < 2:
            continue
        if _is_low_information_tokens(text_tokens):
            continue
        signature = _signature_from_tokens(text_tokens)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        token_set = frozenset(text_tokens)
        prefix_tokens = tuple(text_tokens[:2])
        phrase_exact = 1.0 if query_key and query_key in text.casefold() else 0.0
        token_coverage = 0.0
        if query_token_set:
            token_coverage = len(token_set & query_token_set) / max(
                1, len(query_token_set)
            )
        length_quality = _length_quality(len(text))
        punct_quality = _punct_quality(text)
        bm25 = _bm25_value(index=index, values=bm25_scores)
        raw.append(
            (
                Example(en=text),
                signature,
                token_set,
                prefix_tokens,
                bm25,
                phrase_exact,
                token_coverage,
                length_quality + punct_quality,
            )
        )
        if len(raw) >= candidate_cap:
            break

    if not raw:
        return []

    relevance_from_bm25 = _bm25_relevance([item[4] for item in raw])
    candidates: list[_Candidate] = []
    for index, item in enumerate(raw):
        (
            example,
            signature,
            token_set,
            prefix_tokens,
            _,
            phrase_exact,
            token_cov,
            quality_sum,
        ) = item
        relevance = (
            0.55 * relevance_from_bm25[index]
            + 0.15 * phrase_exact
            + 0.10 * token_cov
            + 0.20 * quality_sum
        )
        candidates.append(
            _Candidate(
                example=example,
                signature=signature,
                token_set=token_set,
                prefix_tokens=prefix_tokens,
                relevance=relevance,
            )
        )
    return candidates


def _is_low_information_tokens(tokens: list[str]) -> bool:
    if not tokens:
        return True
    diversity = len(set(tokens)) / len(tokens)
    if diversity < 0.34 and len(tokens) >= 4:
        return True
    if len(tokens) <= 3 and any(token in _HIGH_AMBIGUITY_TOKENS for token in tokens):
        return True
    return False


def _signature_from_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""
    collapsed: list[str] = []
    previous = ""
    for token in tokens:
        if token == previous:
            continue
        collapsed.append(token)
        previous = token
    return " ".join(collapsed[:12])


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(text)]


def _jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _candidate_similarity(left: _Candidate, right: _Candidate) -> float:
    jaccard = _jaccard_similarity(left.token_set, right.token_set)
    prefix_overlap = _prefix_overlap(left.prefix_tokens, right.prefix_tokens)
    return (0.8 * jaccard) + (0.2 * prefix_overlap)


def _prefix_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if not left or not right:
        return 0.0
    shared = len(set(left) & set(right))
    return shared / max(len(left), len(right))


def _length_quality(length: int) -> float:
    if 60 <= length <= 110:
        return 1.0
    if 20 <= length <= 140:
        return 0.75
    if 12 <= length <= 180:
        return 0.40
    return 0.10


def _punct_quality(text: str) -> float:
    letters = sum(1 for char in text if char.isalpha())
    if letters <= 0:
        return 0.0
    punct = len(_PUNCT_RE.findall(text))
    ratio = punct / letters
    if ratio > 0.22:
        return 0.0
    if ratio > 0.14:
        return 0.25
    if ratio > 0.08:
        return 0.5
    return 0.75


def _bm25_value(index: int, values: list[float] | None) -> float:
    if values is None or index >= len(values):
        return float(index)
    value = values[index]
    if not math.isfinite(value):
        return float(index)
    return value


def _bm25_relevance(values: list[float]) -> list[float]:
    if not values:
        return []
    min_value = min(values)
    max_value = max(values)
    if max_value <= min_value:
        return [1.0 for _ in values]
    spread = max_value - min_value
    result: list[float] = []
    for value in values:
        normalized = (value - min_value) / spread
        # For BM25 from SQLite FTS5 lower is better.
        result.append(1.0 - normalized)
    return result


def _deterministic_jitter(*, seed: str, signature: str, bucket: int) -> float:
    payload = f"{seed}|{signature}|{bucket}".encode("utf-8", errors="ignore")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    as_int = int.from_bytes(digest, byteorder="big", signed=False)
    return (as_int / (2**64)) * _JITTER_MAX


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0
