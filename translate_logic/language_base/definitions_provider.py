from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import threading
from typing import Final
from urllib.parse import quote

from translate_logic.domain import rules
from translate_logic.text import normalize_text, normalize_whitespace


_MAX_QUERY_WORDS: Final[int] = 5
_SQLITE_CACHE_SIZE_KIB: Final[int] = -2048
_SQLITE_MMAP_BYTES: Final[int] = 67_108_864
_WARMUP_FORMS: Final[tuple[str, ...]] = ("time", "make up")


def default_definitions_base_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return (
        repo_root
        / "translate_logic"
        / "language_base"
        / "offline_language_base"
        / "definitions_pack.sqlite3"
    )


@dataclass(slots=True)
class DefinitionsBaseProvider:
    db_path: Path = default_definitions_base_path()
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
        conn.execute(f"PRAGMA cache_size={_SQLITE_CACHE_SIZE_KIB}")
        conn.execute(f"PRAGMA mmap_size={_SQLITE_MMAP_BYTES}")
        setattr(self._local, "conn", conn)
        return conn

    def get_definitions(self, *, word: str, limit: int) -> tuple[str, ...]:
        if limit <= 0:
            return ()
        if not self.db_path.exists():
            return ()
        normalized = normalize_text(word)
        if not normalized:
            return ()
        if rules.count_words(normalized) > _MAX_QUERY_WORDS:
            return ()
        try:
            conn = self._connect()
            key = _lookup_key(conn, normalized)
            if key is None:
                return ()
            rows = conn.execute(
                "SELECT definition FROM defs WHERE key=? "
                "ORDER BY rank_score DESC "
                "LIMIT ?",
                (key, limit * 2),
            ).fetchall()
        except sqlite3.Error:
            return ()
        return _dedupe_definitions(rows, limit=limit)

    def warmup(self) -> None:
        if not self.db_path.exists():
            return
        try:
            conn = self._connect()
            conn.execute("SELECT 1").fetchone()
            conn.execute("SELECT count(*) FROM defs LIMIT 1").fetchone()
            for form in _WARMUP_FORMS:
                conn.execute(
                    "SELECT key FROM defs_forms WHERE form=? LIMIT 1",
                    (form,),
                ).fetchone()
            conn.execute(
                "SELECT definition FROM defs ORDER BY rank_score DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return


def _lookup_key(conn: sqlite3.Connection, normalized: str) -> str | None:
    row = conn.execute(
        "SELECT key FROM defs_phrases WHERE phrase=? LIMIT 1",
        (normalized,),
    ).fetchone()
    if row is not None:
        return str(row["key"])
    row = conn.execute(
        "SELECT key FROM defs_forms WHERE form=? LIMIT 1",
        (normalized,),
    ).fetchone()
    if row is not None:
        return str(row["key"])
    return normalized


def _dedupe_definitions(rows: list[sqlite3.Row], *, limit: int) -> tuple[str, ...]:
    seen: set[str] = set()
    definitions: list[str] = []
    for row in rows:
        definition = normalize_whitespace(str(row["definition"]))
        if not definition:
            continue
        key = definition.casefold()
        if key in seen:
            continue
        seen.add(key)
        definitions.append(definition)
        if len(definitions) >= limit:
            break
    return tuple(definitions)
