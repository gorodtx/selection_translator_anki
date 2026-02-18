from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import sqlite3
import threading
from typing import Final
from urllib.parse import quote

from translate_logic.shared.example_selection import (
    NoveltyState,
    SelectorStats,
    select_examples_v3,
    selector_stats_snapshot,
)
from translate_logic.infrastructure.language_base.validation import (
    MIN_EXAMPLE_WORDS,
    contains_word,
    is_noisy_example,
    normalize_example_query,
    normalize_spaces,
    word_count,
)
from translate_logic.models import Example

_SQLITE_CACHE_SIZE_KIB: Final[int] = -8192
_SQLITE_MMAP_BYTES: Final[int] = 67_108_864
_WARMUP_TERMS: Final[tuple[str, ...]] = ("time", "make up")
_QUERY_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?"
)
_PHASE_SCORE_OFFSETS: Final[tuple[float, float, float]] = (0.0, 1.4, 3.2)
_TOKEN_QUERY_LIMIT: Final[int] = 6


def default_language_base_path() -> Path:
    return _resolve_examples_db_path("primary.sqlite3")


def default_fallback_language_base_path() -> Path:
    return _resolve_examples_db_path("fallback.sqlite3")


def _resolve_examples_db_path(filename: str) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    candidates = (
        repo_root
        / "translate_logic"
        / "infrastructure"
        / "language_base"
        / "offline_language_base",
        repo_root / "translate_logic" / "language_base" / "offline_language_base",
        repo_root / "offline_language_base",
    )
    for base_dir in candidates:
        candidate = base_dir / filename
        if candidate.exists():
            return candidate
    return candidates[0] / filename


def _fts_phrase_query(text: str) -> str | None:
    normalized = normalize_spaces(text)
    if not normalized:
        return None
    if re.fullmatch(r"[A-Za-z0-9]+", normalized):
        return f"en:{normalized}"
    escaped = normalized.replace('"', '""')
    return f'en:"{escaped}"'


def _fts_query_variants(text: str) -> tuple[str, ...]:
    strict_phrase = _fts_phrase_query(text)
    relaxed_text = normalize_example_query(text)
    relaxed_phrase = _fts_phrase_query(relaxed_text)
    token_query = _fts_token_query(relaxed_text)
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in (strict_phrase, relaxed_phrase, token_query):
        if candidate is None:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        variants.append(candidate)
    return tuple(variants)


def _fts_token_query(text: str) -> str | None:
    tokens = [token.casefold() for token in _QUERY_TOKEN_RE.findall(text)]
    if not tokens:
        return None
    bounded = tokens[:_TOKEN_QUERY_LIMIT]
    clauses = ['en:"' + token.replace('"', '""') + '"' for token in bounded]
    if len(clauses) == 1:
        return clauses[0]
    return " AND ".join(clauses)


@dataclass(slots=True)
class LanguageBaseProvider:
    db_path: Path = default_language_base_path()
    fts_limit: int = 80
    selector_latency_budget_ms: float = 20.0
    _local: threading.local = field(
        default_factory=threading.local, init=False, repr=False
    )
    _novelty_state: NoveltyState = field(default_factory=NoveltyState, init=False)

    @property
    def is_available(self) -> bool:
        return self.db_path.exists()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if isinstance(conn, sqlite3.Connection):
            return conn

        encoded = quote(self.db_path.as_posix(), safe="/")
        uri = f"file:{encoded}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute(f"PRAGMA cache_size={_SQLITE_CACHE_SIZE_KIB}")
        conn.execute(f"PRAGMA mmap_size={_SQLITE_MMAP_BYTES}")
        setattr(self._local, "conn", conn)
        return conn

    def get_examples(self, *, word: str, limit: int) -> tuple[Example, ...]:
        if limit <= 0:
            return ()
        queries = _fts_query_variants(word)
        if not queries:
            return ()
        if not self.db_path.exists():
            return ()
        try:
            conn = self._connect()
            rows = _fetch_rows(
                conn=conn,
                queries=queries,
                limit=self.fts_limit,
            )
        except sqlite3.Error:
            return ()
        return _select_examples(
            rows=rows,
            word=normalize_example_query(word) or normalize_spaces(word),
            limit=limit,
            novelty_state=self._novelty_state,
            latency_budget_ms=self.selector_latency_budget_ms,
            candidate_cap=_candidate_cap(word=word, upper_bound=self.fts_limit),
        )

    def warmup(self) -> None:
        if not self.db_path.exists():
            return
        try:
            conn = self._connect()
            conn.execute("SELECT 1").fetchone()
            conn.execute("SELECT count(*) FROM examples_fts LIMIT 1").fetchone()
            for term in _WARMUP_TERMS:
                queries = _fts_query_variants(term)
                if not queries:
                    continue
                conn.execute(
                    "SELECT en, bm25(examples_fts) AS score FROM examples_fts "
                    "WHERE examples_fts MATCH ? "
                    "ORDER BY score "
                    "LIMIT 1",
                    (queries[0],),
                ).fetchone()
        except sqlite3.Error:
            return

    def selector_stats(self) -> SelectorStats:
        return selector_stats_snapshot()


LanguageBaseExampleProvider = LanguageBaseProvider


def _select_examples(
    *,
    rows: list[tuple[str, float, int]],
    word: str,
    limit: int,
    novelty_state: NoveltyState,
    latency_budget_ms: float,
    candidate_cap: int,
) -> tuple[Example, ...]:
    candidates: list[Example] = []
    bm25_scores: list[float] = []
    seen: set[str] = set()
    for en, score, phase_index in rows:
        en = str(en).strip()
        if not en:
            continue
        if word_count(en) < MIN_EXAMPLE_WORDS:
            continue
        if not contains_word(en, word):
            continue
        if is_noisy_example(en, query=word):
            continue
        key = en.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(Example(en=en))
        phase_offset = _PHASE_SCORE_OFFSETS[
            min(phase_index, len(_PHASE_SCORE_OFFSETS) - 1)
        ]
        bm25_scores.append(float(score) + phase_offset)
        if len(candidates) >= candidate_cap:
            break

    if not candidates:
        return ()
    selected = select_examples_v3(
        candidates,
        query=word,
        limit=limit,
        bm25_scores=bm25_scores,
        candidate_cap=candidate_cap,
        latency_budget_ms=latency_budget_ms,
        novelty_state=novelty_state,
    )
    return tuple(selected)


def _candidate_cap(*, word: str, upper_bound: int) -> int:
    normalized = (normalize_example_query(word) or normalize_spaces(word)).casefold()
    words = [part for part in normalized.split(" ") if part]
    if not words:
        return min(40, upper_bound)
    if len(words) >= 2:
        return min(48, upper_bound)
    if words[0] in {"a", "i", "x"} or len(words[0]) <= 2:
        return min(40, upper_bound)
    return min(64, upper_bound)


def _fetch_rows(
    *,
    conn: sqlite3.Connection,
    queries: tuple[str, ...],
    limit: int,
) -> list[tuple[str, float, int]]:
    best_rows: dict[str, tuple[str, float, int]] = {}
    phase_limits = _phase_limits(limit=limit, phases=len(queries))
    for phase_index, query in enumerate(queries):
        phase_limit = phase_limits[min(phase_index, len(phase_limits) - 1)]
        rows = conn.execute(
            "SELECT en, bm25(examples_fts) AS score FROM examples_fts "
            "WHERE examples_fts MATCH ? "
            "ORDER BY score "
            "LIMIT ?",
            (query, phase_limit),
        ).fetchall()
        for row in rows:
            en = str(row["en"]).strip()
            if not en:
                continue
            key = normalize_spaces(en).casefold()
            raw_score = row["score"]
            score = float(raw_score) if raw_score is not None else float(phase_limit)
            current = best_rows.get(key)
            if current is None or score < current[1]:
                best_rows[key] = (en, score, phase_index)
    ordered = sorted(best_rows.values(), key=lambda item: (item[2], item[1]))
    return ordered


def _phase_limits(*, limit: int, phases: int) -> tuple[int, ...]:
    if phases <= 1:
        return (max(16, limit),)
    first = max(16, min(limit, max(16, limit // 3)))
    second = max(first, min(limit, max(24, limit // 2)))
    third = max(second, limit)
    values = (first, second, third)
    return values[:phases]
