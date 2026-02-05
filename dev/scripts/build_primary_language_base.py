#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator
from typing import Final
from urllib.parse import quote as url_quote
from urllib.request import Request, urlopen


CORPORA_ORDER: Final[tuple[str, ...]] = (
    "Tatoeba",
    "News-Commentary",
    "GlobalVoices",
    "TED2020",
    "QED",
    "OpenSubtitles",
)

SOURCE_LANG: Final[str] = "en"
TARGET_LANG: Final[str] = "ru"
PREPROCESSING: Final[str] = "moses"

# Cleanup: remove markup and normalize whitespace, but keep "human noise".
_TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
_SSA_RE: Final[re.Pattern[str]] = re.compile(r"{\\\\[^}]+}")

# Common invisible/control characters that break alignment.
_INVISIBLE_RE: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x1F\x7F-\x9F\u200B-\u200D\u2060\uFEFF]"
)

_LAT_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]")
_CYR_RE: Final[re.Pattern[str]] = re.compile(r"[А-Яа-яЁё]")

_REPEATED_PUNCT_RE: Final[re.Pattern[str]] = re.compile(r"([!?.,:;])\1{1,}")
_LEADING_DIALOGUE_DASH_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[-—–]+\s*")

_ALLOWED_PUNCT: Final[set[str]] = {".", ",", "?", "!", ":", ";", "'", "’"}
_END_PUNCT: Final[tuple[str, ...]] = (".", "?", "!")


@dataclass(frozen=True, slots=True)
class BuildLimits:
    max_db_bytes: int
    safety_margin_bytes: int
    commit_every: int
    en_min_words: int
    en_max_words: int
    ru_min_words: int
    ru_max_words: int
    ratio_min: float
    ratio_max: float


def _normalize_spaces(text: str) -> str:
    return " ".join(text.split())


def _word_count(text: str) -> int:
    return len([part for part in text.split() if part])


def _cleanup_text(text: str) -> str:
    cleaned = _TAG_RE.sub("", text)
    cleaned = _SSA_RE.sub("", cleaned)
    cleaned = _INVISIBLE_RE.sub(" ", cleaned)
    cleaned = _LEADING_DIALOGUE_DASH_RE.sub("", cleaned)

    # Drop quotes/dashes/brackets and other noisy punctuation, but keep core
    # sentence punctuation to preserve readability.
    out: list[str] = []
    for ch in cleaned:
        if ch.isalpha() or ch.isdigit() or ch.isspace() or ch in _ALLOWED_PUNCT:
            out.append(ch)
        else:
            out.append(" ")
    cleaned = "".join(out)
    cleaned = _REPEATED_PUNCT_RE.sub(r"\1", cleaned)
    return _normalize_spaces(cleaned)


def _is_valid_pair(en: str, ru: str, *, limits: BuildLimits) -> bool:
    if len(en) < 7 or len(ru) < 7:
        return False
    if not _LAT_RE.search(en):
        return False
    if not _CYR_RE.search(ru):
        return False
    if "�" in en or "�" in ru:
        return False

    en_wc = _word_count(en)
    ru_wc = _word_count(ru)
    if en_wc < limits.en_min_words or en_wc > limits.en_max_words:
        return False
    if ru_wc < limits.ru_min_words or ru_wc > limits.ru_max_words:
        return False
    ratio = ru_wc / en_wc if en_wc else 0.0
    if ratio < limits.ratio_min or ratio > limits.ratio_max:
        return False
    return True


def _sentence_score(en: str) -> int:
    stripped = en.strip()
    if not stripped:
        return -10_000
    score = 0
    if stripped[0].isupper():
        score += 3
    if stripped.endswith(_END_PUNCT):
        score += 3
    if "..." in stripped:
        score -= 2
    letters = sum(1 for ch in stripped if ch.isalpha())
    punct = sum(1 for ch in stripped if ch in {",", ":", ";", ".", "?", "!"})
    if letters > 0 and punct > 0:
        ratio = punct / letters
        if ratio > 0.20:
            score -= 3
        elif ratio > 0.12:
            score -= 1
    return score


def _en_key(en: str) -> str | None:
    folded = _normalize_spaces(en).casefold()
    if not folded:
        return None
    # Keep only letters/digits/apostrophes and spaces.
    tokens: list[str] = []
    current: list[str] = []
    for ch in folded:
        if ch.isalnum() or ch in {"'", "’"}:
            current.append(ch)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))

    # Remove trailing purely-numeric tokens ("table 1" vs "table").
    while tokens and tokens[-1].isdigit():
        tokens.pop()
    if not tokens:
        return None
    return " ".join(tokens)


def _approx_db_bytes(db_path: Path) -> int:
    total = 0
    for path in (
        db_path,
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    ):
        if path.exists():
            total += path.stat().st_size
    return total


def _opus_latest_moses_zip_url(corpus: str) -> str:
    api_url = (
        "https://opus.nlpl.eu/opusapi/"
        f"?source={SOURCE_LANG}&target={TARGET_LANG}"
        f"&corpus={url_quote(corpus)}&preprocessing={PREPROCESSING}"
    )
    req = Request(api_url, headers={"User-Agent": "translator-langbase-builder/1.0"})
    with urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    infos = data.get("corpora") or []
    if not infos:
        raise RuntimeError(f"OPUS API returned no corpora for {corpus!r}")
    for info in infos:
        if info.get("latest") == "True":
            return str(info["url"])
    return str(infos[-1]["url"])


def _download(url: str, *, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    req = Request(url, headers={"User-Agent": "translator-langbase-builder/1.0"})
    with urlopen(req, timeout=120) as resp, tmp.open("wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def _iter_moses_pairs(zip_path: Path) -> Iterator[tuple[str, str]]:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        en_name = next((n for n in names if n.endswith(".en")), None)
        ru_name = next((n for n in names if n.endswith(".ru")), None)
        if en_name is None or ru_name is None:
            raise RuntimeError(f"Unexpected zip layout: {zip_path}")
        with zf.open(en_name) as en_bin, zf.open(ru_name) as ru_bin:
            # Note: TextIOWrapper is intentionally omitted for speed; we decode per
            # line and ignore errors.
            for raw_en, raw_ru in zip(en_bin, ru_bin, strict=False):
                yield (
                    raw_en.decode("utf-8", errors="ignore"),
                    raw_ru.decode("utf-8", errors="ignore"),
                )


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS examples_fts "
        "USING fts5(en, ru UNINDEXED, tokenize='unicode61')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def _write_meta(conn: sqlite3.Connection, *, key: str, value: object) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, str(value))
    )


def build_primary_language_base(
    *,
    out_path: Path,
    tmp_dir: Path,
    corpora: tuple[str, ...] = CORPORA_ORDER,
    limits: BuildLimits,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_out = out_path.with_name(out_path.name + ".tmp")
    seen_db_path = tmp_dir / "seen.sqlite3"
    for ext in ("", "-wal", "-shm"):
        p = tmp_out if not ext else tmp_out.with_name(tmp_out.name + ext)
        if p.exists():
            p.unlink()
    if seen_db_path.exists():
        seen_db_path.unlink()

    conn = sqlite3.connect(tmp_out)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _create_schema(conn)
        # Keep the dedup index out of the primary DB file to avoid inflating its
        # shipped size. We store it in an attached DB under `tmp_dir/`.
        conn.execute("ATTACH DATABASE ? AS seen_db", (str(seen_db_path),))
        conn.execute(
            "CREATE TABLE seen_db.seen ("
            "en_key TEXT PRIMARY KEY, "
            "rowid INTEGER NOT NULL, "
            "score INTEGER NOT NULL"
            ") WITHOUT ROWID"
        )
        conn.commit()

        inserted = 0
        replaced = 0
        skipped = 0
        started = time.time()

        def should_stop() -> bool:
            used = _approx_db_bytes(tmp_out)
            return used >= limits.max_db_bytes - limits.safety_margin_bytes

        for corpus in corpora:
            zip_path = tmp_dir / f"{corpus}.{SOURCE_LANG}-{TARGET_LANG}.txt.zip"
            # Prefer the already-downloaded OPUS zip to keep rebuilds offline and
            # avoid network flakiness. Only query OPUS API if the zip is missing.
            if not zip_path.exists() or zip_path.stat().st_size == 0:
                zip_url = _opus_latest_moses_zip_url(corpus)
                _download(zip_url, dest=zip_path)

            for raw_en, raw_ru in _iter_moses_pairs(zip_path):
                en = _cleanup_text(raw_en)
                ru = _cleanup_text(raw_ru)
                if not en or not ru:
                    skipped += 1
                    continue
                if not _is_valid_pair(en, ru, limits=limits):
                    skipped += 1
                    continue

                key = _en_key(en)
                if key is None:
                    skipped += 1
                    continue
                score = _sentence_score(en)

                row = conn.execute(
                    "SELECT rowid, score FROM seen_db.seen WHERE en_key = ?", (key,)
                ).fetchone()
                if row is None:
                    cur = conn.execute(
                        "INSERT INTO examples_fts(en, ru) VALUES(?, ?)", (en, ru)
                    )
                    conn.execute(
                        "INSERT INTO seen_db.seen(en_key, rowid, score) "
                        "VALUES(?, ?, ?)",
                        (key, int(cur.lastrowid), score),
                    )
                    inserted += 1
                else:
                    old_rowid = int(row[0])
                    old_score = int(row[1])
                    if score <= old_score:
                        skipped += 1
                        continue
                    conn.execute(
                        "DELETE FROM examples_fts WHERE rowid = ?", (old_rowid,)
                    )
                    cur = conn.execute(
                        "INSERT INTO examples_fts(en, ru) VALUES(?, ?)", (en, ru)
                    )
                    conn.execute(
                        "UPDATE seen_db.seen SET rowid = ?, score = ? WHERE en_key = ?",
                        (int(cur.lastrowid), score, key),
                    )
                    replaced += 1

                if (inserted + replaced) % limits.commit_every == 0:
                    conn.commit()
                    if should_stop():
                        break
            conn.commit()
            if should_stop():
                break

        _write_meta(conn, key="source_lang", value=SOURCE_LANG)
        _write_meta(conn, key="target_lang", value=TARGET_LANG)
        _write_meta(conn, key="corpora", value=",".join(corpora))
        _write_meta(conn, key="en_min_words", value=limits.en_min_words)
        _write_meta(conn, key="en_max_words", value=limits.en_max_words)
        _write_meta(conn, key="ru_min_words", value=limits.ru_min_words)
        _write_meta(conn, key="ru_max_words", value=limits.ru_max_words)
        _write_meta(conn, key="ratio_min", value=limits.ratio_min)
        _write_meta(conn, key="ratio_max", value=limits.ratio_max)
        _write_meta(conn, key="max_db_bytes", value=limits.max_db_bytes)
        _write_meta(conn, key="inserted_rows", value=inserted)
        _write_meta(conn, key="replaced_rows", value=replaced)
        _write_meta(conn, key="skipped_rows", value=skipped)
        _write_meta(conn, key="build_seconds", value=round(time.time() - started, 2))
        conn.commit()

        conn.execute("ANALYZE")
        conn.execute("INSERT INTO examples_fts(examples_fts) VALUES('optimize')")
        conn.execute("DETACH DATABASE seen_db")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
        if seen_db_path.exists():
            seen_db_path.unlink()

    # Ensure the shipped DB is a single file (no sidecars).
    for ext in ("-wal", "-shm"):
        side = tmp_out.with_name(tmp_out.name + ext)
        if side.exists():
            side.unlink()
    if out_path.exists():
        out_path.unlink()
    tmp_out.replace(out_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild primary offline SQLite language base from OPUS corpora (en-ru)."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "offline_language_base"
        / "primary.sqlite3",
        help="Output SQLite path.",
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "dev" / "tmp",
        help="Directory for downloaded OPUS zips (gitignored).",
    )
    parser.add_argument(
        "--max-db-bytes",
        type=int,
        default=1_800_000_000,
        help="Hard cap for output DB size (bytes).",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=5_000,
        help="Commit every N accepted rows.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    limits = BuildLimits(
        max_db_bytes=args.max_db_bytes,
        safety_margin_bytes=50_000_000,
        commit_every=args.commit_every,
        en_min_words=8,
        en_max_words=25,
        ru_min_words=8,
        ru_max_words=30,
        ratio_min=0.5,
        ratio_max=2.5,
    )
    try:
        build_primary_language_base(
            out_path=args.out,
            tmp_dir=args.tmp_dir,
            limits=limits,
        )
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
