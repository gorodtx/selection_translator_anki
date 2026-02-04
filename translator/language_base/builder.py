from __future__ import annotations

import argparse
import datetime as _dt
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import quote

from translate_logic.language_base.provider import default_language_base_path
from translate_logic.language_base.validation import (
    MIN_EXAMPLE_WORDS,
    normalize_spaces,
    word_count,
)

_STOPWORDS: Final[set[str]] = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "from",
    "with",
    "without",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "this",
    "that",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
}

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
_SSA_RE: Final[re.Pattern[str]] = re.compile(r"{\\\\[^}]+}")


def _iter_lines(path: Path) -> Iterator[str]:
    """Iterate aligned corpus lines.

    We intentionally support only plain text files here: distribution uses the
    pre-built SQLite language bases, and we don't want archive formats (zip/gz)
    in the code path.
    """
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        yield from f


def _cleanup_subtitle_text(text: str) -> str:
    # Keep "human noise" (typos/profanity), but remove markup artifacts.
    cleaned = _TAG_RE.sub("", text)
    cleaned = _SSA_RE.sub("", cleaned)
    return normalize_spaces(cleaned)


def _anchor_word(text: str, counts: Counter[str]) -> str | None:
    tokens = [t.casefold() for t in _WORD_RE.findall(text)]
    tokens = [t for t in tokens if t not in _STOPWORDS and len(t) >= 3]
    if not tokens:
        return None
    # Prefer less-seen words first; tie-break on longer words for better context.
    return min(tokens, key=lambda t: (counts[t], -len(t), t))


def _create_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS examples_fts "
        "USING fts5(en, ru UNINDEXED, tokenize='unicode61')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


@dataclass(frozen=True, slots=True)
class BuildStats:
    read_rows: int
    inserted_rows: int
    skipped_rows: int


def _approx_db_bytes(db_path: Path) -> int:
    # In WAL mode, most growth happens in the -wal file until checkpoint.
    # Cap using the total on-disk footprint to keep distribution size bounded.
    total = 0
    for path in (
        db_path,
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    ):
        if path.exists():
            total += path.stat().st_size
    return total


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text))


def _write_meta(
    conn: sqlite3.Connection, *, key: str, value: str | int | float | bool
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, str(value))
    )


def _sqlite_file_uri_ro_immutable(path: Path) -> str:
    # file: URIs allow query params like mode=ro and immutable=1.
    quoted = quote(str(path.resolve()), safe="/")
    return f"file:{quoted}?mode=ro&immutable=1"


def build_language_base(
    *,
    en_path: Path,
    ru_path: Path,
    out_path: Path,
    min_words: int = MIN_EXAMPLE_WORDS,
    max_words: int = 24,
    max_per_anchor: int = 40,
    max_rows: int | None = None,
    require_ru_cyrillic: bool = False,
    ratio_min: float = 0.0,
    ratio_max: float = 10.0,
    max_db_bytes: int | None = None,
    safety_margin_bytes: int = 50_000_000,
    commit_every: int = 5_000,
    write_meta: bool = True,
) -> BuildStats:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    counts: Counter[str] = Counter()
    read_rows = 0
    inserted_rows = 0
    skipped_rows = 0
    stop_by_size = False

    conn = sqlite3.connect(out_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _create_db(conn)

        batch: list[tuple[str, str]] = []

        def flush_batch() -> None:
            nonlocal batch
            if not batch:
                return
            conn.executemany("INSERT INTO examples_fts(en, ru) VALUES(?, ?)", batch)
            conn.commit()
            batch = []

        for raw_en, raw_ru in zip(
            _iter_lines(en_path),
            _iter_lines(ru_path),
            strict=False,
        ):
            read_rows += 1
            if max_rows is not None and inserted_rows >= max_rows:
                break

            en = _cleanup_subtitle_text(raw_en)
            ru = _cleanup_subtitle_text(raw_ru)
            if not en or not ru:
                skipped_rows += 1
                continue
            en_wc = word_count(en)
            if en_wc < min_words or en_wc > max_words:
                skipped_rows += 1
                continue
            if require_ru_cyrillic and not _has_cyrillic(ru):
                skipped_rows += 1
                continue
            ru_wc = word_count(ru)
            if ru_wc == 0:
                skipped_rows += 1
                continue
            ratio = ru_wc / en_wc
            if ratio < ratio_min or ratio > ratio_max:
                skipped_rows += 1
                continue

            anchor = _anchor_word(en, counts)
            if anchor is None or counts[anchor] >= max_per_anchor:
                skipped_rows += 1
                continue

            batch.append((en, ru))
            inserted_rows += 1
            counts[anchor] += 1
            if len(batch) >= commit_every:
                flush_batch()
                if max_db_bytes is not None:
                    bytes_used = _approx_db_bytes(out_path)
                    if bytes_used >= max_db_bytes - safety_margin_bytes:
                        stop_by_size = True
                        break

        flush_batch()

        if write_meta:
            _write_meta(conn, key="min_words", value=min_words)
            _write_meta(conn, key="max_words", value=max_words)
            _write_meta(conn, key="max_per_anchor", value=max_per_anchor)
            _write_meta(conn, key="require_ru_cyrillic", value=require_ru_cyrillic)
            _write_meta(conn, key="ratio_min", value=ratio_min)
            _write_meta(conn, key="ratio_max", value=ratio_max)
            if max_db_bytes is not None:
                _write_meta(conn, key="max_db_bytes", value=max_db_bytes)
            _write_meta(conn, key="read_rows", value=read_rows)
            _write_meta(conn, key="inserted_rows", value=inserted_rows)
            _write_meta(conn, key="skipped_rows", value=skipped_rows)
            _write_meta(conn, key="stopped_by_size", value=stop_by_size)
            _write_meta(
                conn,
                key="built_at_utc",
                value=_dt.datetime.now(tz=_dt.UTC).isoformat(timespec="seconds"),
            )
            conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    return BuildStats(
        read_rows=read_rows, inserted_rows=inserted_rows, skipped_rows=skipped_rows
    )


def build_opensubtitles_lite(
    *,
    en_path: Path,
    ru_path: Path,
    out_path: Path,
    max_rows: int | None = None,
    max_db_bytes: int = 1_700_000_000,
    safety_margin_bytes: int = 50_000_000,
) -> BuildStats:
    # Re-create to ensure the schema stays deterministic (and compact).
    if out_path.exists():
        out_path.unlink()
    for ext in ("-wal", "-shm"):
        side = out_path.with_name(out_path.name + ext)
        if side.exists():
            side.unlink()
    return build_language_base(
        en_path=en_path,
        ru_path=ru_path,
        out_path=out_path,
        min_words=MIN_EXAMPLE_WORDS,
        max_words=9,
        max_per_anchor=800,
        max_rows=max_rows,
        require_ru_cyrillic=True,
        ratio_min=0.5,
        ratio_max=2.5,
        max_db_bytes=max_db_bytes,
        safety_margin_bytes=safety_margin_bytes,
    )


def migrate_drop_source_column(*, in_path: Path, out_path: Path) -> BuildStats:
    """Create a copy of an existing DB without the legacy `source` column.

    This is a one-time migration helper: early versions of our FTS schema stored a
    redundant `source` column on every row. It has no functional value and makes
    the DB larger. This function rewrites the DB into the compact schema
    (en, ru UNINDEXED) and copies meta excluding the `source` key.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build into a temp file and then atomically replace the target DB. This keeps
    # `out_path` usable even if the migration fails midway.
    tmp_out = out_path.with_name(out_path.name + ".tmp")
    if tmp_out.exists():
        tmp_out.unlink()
    for ext in ("-wal", "-shm"):
        side = tmp_out.with_name(tmp_out.name + ext)
        if side.exists():
            side.unlink()

    conn = sqlite3.connect(tmp_out, uri=True)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _create_db(conn)
        conn.execute(
            "ATTACH DATABASE ? AS old",
            (_sqlite_file_uri_ro_immutable(in_path),),
        )
        conn.execute(
            "INSERT INTO examples_fts(en, ru) SELECT en, ru FROM old.examples_fts"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) "
            "SELECT key, value FROM old.meta WHERE key != 'source'"
        )
        conn.commit()
        conn.execute("DETACH DATABASE old")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    # Ensure no temp sidecar files are left behind (distribution expects a single file).
    for ext in ("-wal", "-shm"):
        side = tmp_out.with_name(tmp_out.name + ext)
        if side.exists():
            side.unlink()

    tmp_out.replace(out_path)
    for ext in ("-wal", "-shm"):
        side = out_path.with_name(out_path.name + ext)
        if side.exists():
            side.unlink()

    # Prefer meta counters from the input DB if present (count(*) on large FTS is costly).
    read_rows = 0
    inserted_rows = 0
    skipped_rows = 0
    src = sqlite3.connect(_sqlite_file_uri_ro_immutable(in_path), uri=True)
    try:
        for key, value in src.execute("SELECT key, value FROM meta"):
            if key == "read_rows":
                read_rows = int(value)
            elif key == "inserted_rows":
                inserted_rows = int(value)
            elif key == "skipped_rows":
                skipped_rows = int(value)
    except sqlite3.OperationalError:
        # No meta table in older/hand-crafted DBs.
        pass
    finally:
        src.close()

    return BuildStats(
        read_rows=read_rows, inserted_rows=inserted_rows, skipped_rows=skipped_rows
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local SQLite language base from aligned subtitle corpora.\n\n"
            "Recommended source for 'human' examples: OPUS OpenSubtitles (en-ru).\n"
            "Download and unpack aligned text files and pass them via --en/--ru."
        )
    )
    parser.add_argument(
        "--preset",
        choices=("generic", "opensubtitles_lite", "migrate_drop_source"),
        default="generic",
        help=(
            "Build preset. 'opensubtitles_lite' applies strict filters and a byte cap "
            "suitable for distribution."
        ),
    )
    parser.add_argument(
        "--en",
        type=Path,
        required=False,
        help="English text file (one sentence per line).",
    )
    parser.add_argument(
        "--ru", type=Path, required=False, help="Russian text file (aligned to --en)."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=default_language_base_path(),
        help="Output SQLite path.",
    )
    parser.add_argument(
        "--in-db",
        type=Path,
        default=None,
        help="Input SQLite DB (migrate_drop_source preset).",
    )
    # No corpus downloads here; the repo ships only SQLite bases.
    parser.add_argument("--min-words", type=int, default=MIN_EXAMPLE_WORDS)
    parser.add_argument("--max-words", type=int, default=24)
    parser.add_argument("--max-per-anchor", type=int, default=40)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--require-ru-cyrillic",
        action="store_true",
        help="Skip rows where RU side has no Cyrillic characters.",
    )
    parser.add_argument(
        "--ratio-min",
        type=float,
        default=0.0,
        help="Minimum RU_words/EN_words ratio.",
    )
    parser.add_argument(
        "--ratio-max",
        type=float,
        default=10.0,
        help="Maximum RU_words/EN_words ratio.",
    )
    parser.add_argument(
        "--max-db-bytes",
        type=int,
        default=None,
        help="Stop building once the SQLite on-disk footprint reaches this size.",
    )
    parser.add_argument(
        "--safety-margin-bytes",
        type=int,
        default=50_000_000,
        help="Stop slightly before max-db-bytes to avoid overshoot.",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=5_000,
        help="Commit inserts every N rows (speed vs size-check granularity).",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.preset == "migrate_drop_source":
        if args.in_db is None:
            raise SystemExit("--in-db is required for migrate_drop_source preset")
        stats = migrate_drop_source_column(in_path=args.in_db, out_path=args.out)
    elif args.preset == "opensubtitles_lite":
        if args.en is None or args.ru is None:
            raise SystemExit("--en and --ru are required for opensubtitles_lite preset")
        stats = build_opensubtitles_lite(
            en_path=args.en,
            ru_path=args.ru,
            out_path=args.out,
            max_rows=args.max_rows,
            max_db_bytes=args.max_db_bytes or 1_700_000_000,
            safety_margin_bytes=args.safety_margin_bytes,
        )
    else:
        if args.en is None or args.ru is None:
            raise SystemExit("--en and --ru are required for generic preset")
        stats = build_language_base(
            en_path=args.en,
            ru_path=args.ru,
            out_path=args.out,
            min_words=args.min_words,
            max_words=args.max_words,
            max_per_anchor=args.max_per_anchor,
            max_rows=args.max_rows,
            require_ru_cyrillic=args.require_ru_cyrillic,
            ratio_min=args.ratio_min,
            ratio_max=args.ratio_max,
            max_db_bytes=args.max_db_bytes,
            safety_margin_bytes=args.safety_margin_bytes,
            commit_every=args.commit_every,
        )
    print(
        f"read={stats.read_rows} inserted={stats.inserted_rows} skipped={stats.skipped_rows} out={args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
