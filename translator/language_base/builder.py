from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import io
import re
import sqlite3
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from translate_logic.language_base.provider import default_language_base_path
from translate_logic.language_base.validation import (
    MIN_EXAMPLE_WORDS,
    normalize_spaces,
    word_count,
)
from translate_logic.models import ExampleSource

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


@dataclass(frozen=True, slots=True)
class OpusDownload:
    corpus: str
    url: str
    version: str


def _iter_lines(path: Path, *, zip_member_suffix: str | None) -> Iterator[str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
            yield from f
        return
    if path.suffix == ".zip":
        if zip_member_suffix is None:
            raise ValueError("zip_member_suffix is required for .zip inputs")
        with zipfile.ZipFile(path) as zf:
            member = next(
                (
                    name
                    for name in zf.namelist()
                    if name.endswith(zip_member_suffix) and not name.endswith("/")
                ),
                None,
            )
            if member is None:
                raise FileNotFoundError(
                    f"Zip does not contain a member ending with {zip_member_suffix!r}: {path}"
                )
            with zf.open(member, "r") as raw:
                wrapper = io.TextIOWrapper(raw, encoding="utf-8", errors="ignore")
                yield from wrapper
        return
    else:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            yield from f
        return


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
        "USING fts5(en, ru UNINDEXED, source UNINDEXED, tokenize='unicode61')"
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


def build_language_base(
    *,
    en_path: Path,
    ru_path: Path,
    out_path: Path,
    source: ExampleSource,
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

        batch: list[tuple[str, str, str]] = []

        def flush_batch() -> None:
            nonlocal batch
            if not batch:
                return
            conn.executemany(
                "INSERT INTO examples_fts(en, ru, source) VALUES(?, ?, ?)", batch
            )
            conn.commit()
            batch = []

        for raw_en, raw_ru in zip(
            _iter_lines(en_path, zip_member_suffix=".en"),
            _iter_lines(ru_path, zip_member_suffix=".ru"),
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

            batch.append((en, ru, source.value))
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
            _write_meta(conn, key="source", value=source.value)
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
    return build_language_base(
        en_path=en_path,
        ru_path=ru_path,
        out_path=out_path,
        source=ExampleSource.OPUS_OPEN_SUBTITLES,
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local SQLite language base from aligned subtitle corpora.\n\n"
            "Recommended source for 'human' examples: OPUS OpenSubtitles (en-ru).\n"
            "Download the aligned text files (or .gz) and pass them via --en/--ru."
        )
    )
    parser.add_argument(
        "--preset",
        choices=("generic", "opensubtitles_lite"),
        default="generic",
        help=(
            "Build preset. 'opensubtitles_lite' applies strict filters and a byte cap "
            "suitable for distribution."
        ),
    )
    parser.add_argument(
        "--en",
        type=Path,
        required=True,
        help="English text file (one sentence per line).",
    )
    parser.add_argument(
        "--ru", type=Path, required=True, help="Russian text file (aligned to --en)."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=default_language_base_path(),
        help="Output SQLite path.",
    )
    parser.add_argument(
        "--source",
        choices=[e.value for e in ExampleSource],
        default=ExampleSource.OPUS_OPEN_SUBTITLES.value,
        help="Example source tag saved in DB.",
    )
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


def resolve_opus_moses_url(*, corpus: str) -> OpusDownload:
    import json
    import urllib.request

    url = (
        f"https://opus.nlpl.eu/opusapi/?corpus={corpus}"
        "&source=en&target=ru&preprocessing=moses&version=latest&format=json"
    )
    with urllib.request.urlopen(url) as r:  # noqa: S310 (trusted host, read-only)
        payload = json.loads(r.read().decode("utf-8"))
    corpora = payload.get("corpora", [])
    if not corpora:
        raise ValueError(f"OPUS API returned no entries for corpus={corpus!r}")
    first = corpora[0]
    download_url = str(first.get("url", "")).strip()
    version = str(first.get("version", "")).strip()
    if not download_url:
        raise ValueError(f"OPUS API entry has no url for corpus={corpus!r}")
    return OpusDownload(corpus=corpus, url=download_url, version=version)


def download_to(*, url: str, out_path: Path) -> None:
    import urllib.request

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with urllib.request.urlopen(url) as r, tmp.open("wb") as f:  # noqa: S310
        f.write(r.read())
    tmp.replace(out_path)


def build_fallback_language_base(
    *,
    out_path: Path,
    tmp_dir: Path,
    max_rows: int | None = None,
) -> BuildStats:
    """Build a small fallback DB from OPUS (QED + Tatoeba).

    This DB is intended to be distributed with the repo and provide examples
    when the primary OpenSubtitles lite DB misses.
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    total_read = 0
    total_inserted = 0
    total_skipped = 0

    # Re-create to keep it deterministic.
    if out_path.exists():
        out_path.unlink()
    for ext in ("-wal", "-shm"):
        side = out_path.with_name(out_path.name + ext)
        if side.exists():
            side.unlink()

    sources: list[tuple[str, ExampleSource]] = [
        ("QED", ExampleSource.OPUS_QED),
        ("Tatoeba", ExampleSource.OPUS_TATOEBA),
    ]
    for corpus, source in sources:
        zip_path = tmp_dir / f"{corpus}.en-ru.txt.zip"
        if not zip_path.exists():
            download = resolve_opus_moses_url(corpus=corpus)
            download_to(url=download.url, out_path=zip_path)

        stats = build_language_base(
            en_path=zip_path,
            ru_path=zip_path,
            out_path=out_path,
            source=source,
            min_words=MIN_EXAMPLE_WORDS,
            max_words=9,
            max_per_anchor=200,
            max_rows=max_rows,
            require_ru_cyrillic=True,
            ratio_min=0.5,
            ratio_max=2.5,
            commit_every=5_000,
            write_meta=False,
        )
        total_read += stats.read_rows
        total_inserted += stats.inserted_rows
        total_skipped += stats.skipped_rows

    conn = sqlite3.connect(out_path)
    try:
        _write_meta(conn, key="source", value="fallback")
        _write_meta(conn, key="corpora", value="QED,Tatoeba")
        _write_meta(conn, key="read_rows", value=total_read)
        _write_meta(conn, key="inserted_rows", value=total_inserted)
        _write_meta(conn, key="skipped_rows", value=total_skipped)
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
        read_rows=total_read,
        inserted_rows=total_inserted,
        skipped_rows=total_skipped,
    )


def main() -> int:
    args = _build_parser().parse_args()
    if args.preset == "opensubtitles_lite":
        stats = build_opensubtitles_lite(
            en_path=args.en,
            ru_path=args.ru,
            out_path=args.out,
            max_rows=args.max_rows,
            max_db_bytes=args.max_db_bytes or 1_700_000_000,
            safety_margin_bytes=args.safety_margin_bytes,
        )
    else:
        stats = build_language_base(
            en_path=args.en,
            ru_path=args.ru,
            out_path=args.out,
            source=ExampleSource(args.source),
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
