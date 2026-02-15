from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import sqlite3
import threading
from typing import Final
from urllib.parse import quote

from translate_logic.example_selection import (
    NoveltyState,
    SelectorStats,
    select_examples_v3,
    selector_stats_snapshot,
)
from translate_logic.language_base.validation import (
    MIN_EXAMPLE_WORDS,
    contains_word,
    normalize_spaces,
    word_count,
)
from translate_logic.models import Example

_SQLITE_CACHE_SIZE_KIB: Final[int] = -8192
_SQLITE_MMAP_BYTES: Final[int] = 67_108_864
_WARMUP_TERMS: Final[tuple[str, ...]] = ("time", "make up")


def default_language_base_path() -> Path:
    return _resolve_examples_db_path("primary.sqlite3")


def default_fallback_language_base_path() -> Path:
    return _resolve_examples_db_path("fallback.sqlite3")


def _resolve_examples_db_path(filename: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    candidates = (
        repo_root / "translate_logic" / "language_base" / "offline_language_base",
        repo_root / "offline_language_base",
    )
    for base_dir in candidates:
        candidate = base_dir / filename
        if candidate.exists():
            return candidate
    return candidates[0] / filename


def _fts_query(text: str) -> str | None:
    normalized = normalize_spaces(text)
    if not normalized:
        return None
    if re.fullmatch(r"[A-Za-z0-9]+", normalized):
        return f"en:{normalized}"
    escaped = normalized.replace('"', '""')
    return f'en:"{escaped}"'


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
        query = _fts_query(word)
        if query is None:
            return ()
        if not self.db_path.exists():
            return ()
        try:
            conn = self._connect()
            rows = conn.execute(
                "SELECT en, bm25(examples_fts) AS score FROM examples_fts "
                "WHERE examples_fts MATCH ? "
                "ORDER BY score "
                "LIMIT ?",
                (query, self.fts_limit),
            ).fetchall()
        except sqlite3.Error:
            return ()
        return _select_examples(
            rows=rows,
            word=word,
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
                query = _fts_query(term)
                if query is None:
                    continue
                conn.execute(
                    "SELECT en, bm25(examples_fts) AS score FROM examples_fts "
                    "WHERE examples_fts MATCH ? "
                    "ORDER BY score "
                    "LIMIT 1",
                    (query,),
                ).fetchone()
        except sqlite3.Error:
            return

    def selector_stats(self) -> SelectorStats:
        return selector_stats_snapshot()


LanguageBaseExampleProvider = LanguageBaseProvider


def _select_examples(
    *,
    rows: list[sqlite3.Row],
    word: str,
    limit: int,
    novelty_state: NoveltyState,
    latency_budget_ms: float,
    candidate_cap: int,
) -> tuple[Example, ...]:
    candidates: list[Example] = []
    bm25_scores: list[float] = []
    seen: set[str] = set()
    for row in rows:
        en = str(row["en"]).strip()
        if not en:
            continue
        if word_count(en) < MIN_EXAMPLE_WORDS:
            continue
        if not contains_word(en, word):
            continue
        key = en.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(Example(en=en))
        score_raw = row["score"]
        score = float(score_raw) if score_raw is not None else float(len(candidates))
        bm25_scores.append(score)
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
    normalized = normalize_spaces(word).casefold()
    words = [part for part in normalized.split(" ") if part]
    if not words:
        return min(40, upper_bound)
    if len(words) >= 2:
        return min(48, upper_bound)
    if words[0] in {"a", "i", "x"} or len(words[0]) <= 2:
        return min(40, upper_bound)
    return min(64, upper_bound)
