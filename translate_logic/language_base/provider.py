from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import sqlite3
import threading
from typing import Final
from urllib.parse import quote

from translate_logic.language_base.validation import (
    MIN_EXAMPLE_WORDS,
    contains_word,
    normalize_spaces,
    word_count,
)
from translate_logic.models import Example


def default_language_base_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "offline_language_base" / "primary.sqlite3"


def default_fallback_language_base_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "offline_language_base" / "fallback.sqlite3"


_PUNCT_RE: Final[re.Pattern[str]] = re.compile(r"[\"'“”«»()\\[\\]{}<>—–-]")
_END_PUNCT: Final[tuple[str, ...]] = (".", "?", "!")


def _fts_query(text: str) -> str | None:
    normalized = normalize_spaces(text)
    if not normalized:
        return None
    if re.fullmatch(r"[A-Za-z0-9]+", normalized):
        return f"en:{normalized}"
    escaped = normalized.replace('"', '""')
    return f'en:"{escaped}"'


def _sentence_score(en: str) -> int:
    stripped = en.strip()
    if not stripped:
        return -10_000
    score = 0
    if stripped[0].isupper():
        score += 3
    if stripped.endswith(_END_PUNCT):
        score += 3
    letters = sum(1 for ch in stripped if ch.isalpha())
    punct = len(_PUNCT_RE.findall(stripped))
    if letters > 0 and punct > 0:
        ratio = punct / letters
        if ratio > 0.20:
            score -= 3
        elif ratio > 0.12:
            score -= 1
    return score


@dataclass(slots=True)
class LanguageBaseProvider:
    db_path: Path = default_language_base_path()
    fts_limit: int = 200
    _local: threading.local = field(
        default_factory=threading.local, init=False, repr=False
    )

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
        conn.execute("PRAGMA cache_size=-100000")
        conn.execute("PRAGMA mmap_size=268435456")
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
                "SELECT en, ru FROM examples_fts "
                "WHERE examples_fts MATCH ? "
                "ORDER BY bm25(examples_fts) "
                "LIMIT ?",
                (query, self.fts_limit),
            ).fetchall()
        except sqlite3.Error:
            return ()
        return _select_examples(rows=rows, word=word, limit=limit)

    def warmup(self) -> None:
        if not self.db_path.exists():
            return
        try:
            conn = self._connect()
            conn.execute("SELECT 1").fetchone()
            conn.execute("SELECT count(*) FROM examples_fts LIMIT 1").fetchone()
        except sqlite3.Error:
            return


LanguageBaseExampleProvider = LanguageBaseProvider


def _select_examples(
    *,
    rows: list[sqlite3.Row],
    word: str,
    limit: int,
) -> tuple[Example, ...]:
    scored: list[tuple[int, int, Example]] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        en = str(row["en"]).strip()
        ru = str(row["ru"]).strip()
        if not en or not ru:
            continue
        if word_count(en) < MIN_EXAMPLE_WORDS:
            continue
        if not contains_word(en, word):
            continue
        key = (en.casefold(), ru.casefold())
        if key in seen:
            continue
        seen.add(key)
        example = Example(en=en, ru=ru)
        scored.append((_sentence_score(en), index, example))

    if not scored:
        return ()

    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(example for _, _, example in scored[:limit])
