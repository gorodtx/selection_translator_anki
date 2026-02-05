#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import gzip
import heapq
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
import unicodedata
from urllib.request import Request, urlopen


KAIKKI_URL = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl"

_LAT_RE = re.compile(r"[A-Za-z]")
_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_PARENS_RE = re.compile(r"\([^)]*\)")
_BRACKETS_RE = re.compile(r"\[[^]]*\]")
_STRIP_COMBINING: frozenset[str] = frozenset(
    {
        # Stress marks are commonly encoded as combining acute/grave accents.
        # NOTE: Do NOT drop all combining marks: Wiktionary/Kaikki may use
        # decomposed forms for letters like "й" (и + breve) and "ё" (е + diaeresis).
        "\u0301",  # COMBINING ACUTE ACCENT
        "\u0300",  # COMBINING GRAVE ACCENT
        "\u0341",  # COMBINING ACUTE TONE MARK
        "\u0340",  # COMBINING GRAVE TONE MARK
    }
)

# A small list to guarantee we always ship clean variants for common modals
# and auxiliaries, even if the generic POS filters are too strict.
_FORCED_WORD_KEYS: set[str] = {
    "can",
    "could",
    "may",
    "might",
    "must",
    "shall",
    "should",
    "will",
    "would",
    "ought",
    "need",
    "dare",
}

# Parts of speech we consider "function-ish". These are exactly where
# corpus-derived variants are the noisiest and lexicon helps the most.
_FUNCTION_POS: frozenset[str] = frozenset(
    {
        # Full names.
        "conjunction",
        "particle",
        "interjection",
        "preposition",
        "pronoun",
        "determiner",
        "adverb",
        "auxiliary",
        # Common Wiktionary/Wiktextract abbreviations.
        "conj",
        "part",
        "intj",
        "prep",
        "pron",
        "det",
        "adv",
        "aux",
    }
)

_PHRASAL_PARTICLES: frozenset[str] = frozenset(
    {
        "up",
        "down",
        "out",
        "in",
        "on",
        "off",
        "over",
        "under",
        "away",
        "back",
        "around",
        "about",
        "through",
        "into",
        "onto",
        "from",
        "with",
        "without",
    }
)

_IDIOM_STARTERS: frozenset[str] = frozenset(
    {
        "by",
        "in",
        "on",
        "at",
        "as",
        "for",
        "to",
        "from",
        "with",
        "without",
        "out",
        "up",
        "down",
        "over",
        "under",
        "about",
        "around",
        "through",
        "into",
        "onto",
    }
)


@dataclass(frozen=True, slots=True)
class Limits:
    max_db_bytes: int
    safety_margin_bytes: int
    max_phrase_keys: int
    max_word_keys: int
    max_translations_per_key: int
    commit_every: int


def _normalize_spaces(value: str) -> str:
    return " ".join(value.split())


def _normalize_key(value: str) -> str:
    normalized = _normalize_spaces(value)
    if not normalized:
        return ""
    # Normalize apostrophes: users type "'", corpora sometimes contain "’".
    normalized = normalized.replace("’", "'")
    return normalized.casefold()


def _clean_ru_translation(value: str) -> str:
    cleaned = _normalize_spaces(value)
    cleaned = _PARENS_RE.sub("", cleaned)
    cleaned = _BRACKETS_RE.sub("", cleaned)
    cleaned = cleaned.replace("’", "'")
    # Kaikki/Wiktionary frequently contain stress marks as combining accents.
    # Strip stress marks but keep other combining marks so NFC can rebuild
    # letters like "й"/"ё" when they appear in decomposed form.
    cleaned = unicodedata.normalize("NFD", cleaned)
    cleaned = "".join(ch for ch in cleaned if ch not in _STRIP_COMBINING)
    cleaned = unicodedata.normalize("NFC", cleaned)
    cleaned = cleaned.strip()
    cleaned = cleaned.strip(" \"'«».,;:!?-–—")
    return _normalize_spaces(cleaned)


def _is_good_ru(value: str) -> bool:
    if not value or len(value) < 2:
        return False
    if not _CYR_RE.search(value):
        return False
    if _LAT_RE.search(value):
        return False
    if "�" in value:
        return False
    if len(value) > 80:
        return False
    # Avoid extremely long multiword "translations"; those are often glosses.
    if len(value.split()) > 7:
        return False
    return True


def _ru_variants_from_translations(translations: object) -> list[str]:
    if not isinstance(translations, list):
        return []
    out: list[str] = []
    for item in translations:
        if not isinstance(item, dict):
            continue
        lang_code = item.get("lang_code") or item.get("code")
        if lang_code != "ru":
            continue
        raw = item.get("word")
        if not isinstance(raw, str):
            continue
        cleaned = _clean_ru_translation(raw)
        if not _is_good_ru(cleaned):
            continue
        out.append(cleaned)
    return out


def _ru_variants_from_obj(obj: dict[str, object]) -> list[str]:
    # Translations can appear either at the top-level or inside senses.
    out: list[str] = []
    out.extend(_ru_variants_from_translations(obj.get("translations")))
    senses = obj.get("senses")
    if isinstance(senses, list):
        for sense in senses:
            if not isinstance(sense, dict):
                continue
            out.extend(_ru_variants_from_translations(sense.get("translations")))
    return out


def _is_phrase_key(key: str) -> bool:
    # Phrases = multiword only. Contractions (can't) are treated as "word keys".
    return " " in key


def _looks_like_ascii_phrase(key: str) -> bool:
    for ch in key:
        if not ch.isascii():
            return False
        if ch.isalpha() or ch in {" ", "'", "-"}:
            continue
        return False
    return True


def _is_interesting_word_key(*, key: str, pos: str | None) -> bool:
    if not key:
        return False
    if key in _FORCED_WORD_KEYS:
        return True
    # Contractions, hyphenated compounds, etc.
    if "'" in key or "-" in key:
        return True
    if pos is None:
        return False
    return pos.casefold() in _FUNCTION_POS


def _dedup_sorted(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        key = raw.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    out.sort(key=lambda v: (len(v.split()), len(v), v))
    return out


def _phrase_score(*, key: str, ru: list[str]) -> int:
    tokens = key.split()
    score = 0
    if 2 <= len(tokens) <= 5:
        score += 2
    if len(tokens) == 2 and tokens[1] in _PHRASAL_PARTICLES:
        score += 6
    score += min(8, len(ru))  # more translations => likely a stable entry
    return score


def _phrase_base_score(key: str) -> int:
    tokens = key.split()
    if not (2 <= len(tokens) <= 5):
        return -1
    if any(tok.isdigit() for tok in tokens):
        return -1
    if not _looks_like_ascii_phrase(key):
        return -1
    score = 0
    if tokens[0] in _IDIOM_STARTERS:
        score += 4
    if len(tokens) == 2 and tokens[1] in _PHRASAL_PARTICLES:
        score += 8
    elif any(tok in _PHRASAL_PARTICLES for tok in tokens[1:]):
        score += 4
    # Shorter phrases are more likely to be useful "dictionary entries".
    score += max(0, 6 - len(tokens))
    return score


def _download(url: str, *, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    # Kaikki can be served either as raw JSONL (~2.8GB) or as gzip-compressed
    # transfer encoding (~450MB). Always request gzip to keep downloads sane.
    req = Request(
        url,
        headers={
            "User-Agent": "translator-wiktionary-lexicon/1.0",
            "Accept-Encoding": "gzip",
        },
    )
    with urlopen(req, timeout=120) as resp, tmp.open("wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def _iter_kaikki_jsonl(path: Path) -> Iterator[dict[str, object]]:
    # If the downloaded file is gzip-compressed, stream-decompress it.
    with path.open("rb") as probe:
        magic = probe.read(2)
    opener = gzip.open if magic == b"\x1f\x8b" else Path.open
    with opener(path, "rb") as f:  # type: ignore[call-arg]
        for raw in f:  # type: ignore[assignment]
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


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


def _create_new_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS lexicon_new")
    conn.execute("DROP TABLE IF EXISTS lexicon_forms_new")
    conn.execute(
        "CREATE TABLE lexicon_new (key TEXT PRIMARY KEY, ru_json TEXT NOT NULL) "
        "WITHOUT ROWID"
    )
    conn.execute(
        "CREATE TABLE lexicon_forms_new (form TEXT PRIMARY KEY, key TEXT NOT NULL) "
        "WITHOUT ROWID"
    )


def _finalize_swap(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS lexicon")
    conn.execute("DROP TABLE IF EXISTS lexicon_forms")
    conn.execute("ALTER TABLE lexicon_new RENAME TO lexicon")
    conn.execute("ALTER TABLE lexicon_forms_new RENAME TO lexicon_forms")


def build_lexicon_pack(*, db_path: Path, tmp_dir: Path, limits: Limits) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src_path = tmp_dir / "kaikki-english.jsonl.gz"
    _download(KAIKKI_URL, dest=src_path)

    # Collect selected entries in memory; keys are limited (<= 250k typical),
    # so this remains manageable while allowing us to merge POS lines.
    phrases: dict[str, set[str]] = {}
    phrase_heap: list[tuple[int, str]] = []
    words: dict[str, set[str]] = {}
    forms: dict[str, str] = {}

    def add_item(
        mapping: dict[str, set[str]],
        key: str,
        ru: list[str],
        max_keys: int,
    ) -> None:
        if key in mapping:
            mapping[key].update(ru)
            return
        if len(mapping) >= max_keys and key not in _FORCED_WORD_KEYS:
            return
        mapping[key] = set(ru)

    def add_phrase(key: str, ru: list[str]) -> None:
        if key in phrases:
            phrases[key].update(ru)
            return
        score = _phrase_base_score(key)
        if score < 0:
            return
        if len(phrases) < limits.max_phrase_keys:
            phrases[key] = set(ru)
            heapq.heappush(phrase_heap, (score, key))
            return
        min_score, min_key = phrase_heap[0]
        if score <= min_score:
            return
        heapq.heapreplace(phrase_heap, (score, key))
        phrases.pop(min_key, None)
        phrases[key] = set(ru)

    processed = 0
    started_parse = time.time()
    for obj in _iter_kaikki_jsonl(src_path):
        processed += 1
        if processed % 200_000 == 0:
            elapsed = round(time.time() - started_parse, 1)
            print(
                f"[kaikki] lines={processed:,} words={len(words):,} "
                f"phrases={len(phrases):,} forms={len(forms):,} "
                f"elapsed={elapsed}s",
                file=sys.stderr,
            )
        raw_word = obj.get("word")
        if not isinstance(raw_word, str):
            continue
        key = _normalize_key(raw_word)
        if not key or len(key) > 64:
            continue
        if not _LAT_RE.search(key):
            continue

        ru = _ru_variants_from_obj(obj)
        if not ru:
            continue

        if _is_phrase_key(key):
            add_phrase(key, ru)
            continue

        pos = obj.get("pos")
        pos_str = str(pos) if isinstance(pos, str) else None
        if not _is_interesting_word_key(key=key, pos=pos_str):
            continue
        add_item(words, key, ru, limits.max_word_keys)

        raw_forms = obj.get("forms")
        if not isinstance(raw_forms, list):
            continue
        for item in raw_forms:
            if not isinstance(item, dict):
                continue
            form_raw = item.get("form")
            if not isinstance(form_raw, str):
                continue
            form = _normalize_key(form_raw)
            if not form or form == key:
                continue
            # Keep mapping compact; we only store forms for keys we already keep.
            if form not in forms:
                forms[form] = key

    # Prepare the final list in priority order so we stop safely under the DB cap.
    merged: list[tuple[int, str, list[str]]] = []
    for key, ru_set in words.items():
        ru_sorted = _dedup_sorted(ru_set)[: limits.max_translations_per_key]
        if not ru_sorted:
            continue
        score = 1_000 if key in _FORCED_WORD_KEYS else 100
        merged.append((score, key, ru_sorted))
    for key, ru_set in phrases.items():
        ru_sorted = _dedup_sorted(ru_set)[: limits.max_translations_per_key]
        if not ru_sorted:
            continue
        merged.append((_phrase_score(key=key, ru=ru_sorted), key, ru_sorted))

    merged.sort(key=lambda row: row[0], reverse=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _create_new_tables(conn)
        conn.commit()

        inserted = 0
        started = time.time()

        def should_stop() -> bool:
            used = _approx_db_bytes(db_path)
            return used >= limits.max_db_bytes - limits.safety_margin_bytes

        for _, key, ru_sorted in merged:
            if should_stop():
                break
            conn.execute(
                "INSERT OR REPLACE INTO lexicon_new(key, ru_json) VALUES(?, ?)",
                (key, json.dumps(ru_sorted, ensure_ascii=False)),
            )
            inserted += 1
            if inserted % limits.commit_every == 0:
                conn.commit()
        conn.commit()

        for form, key in forms.items():
            if should_stop():
                break
            conn.execute(
                "INSERT OR IGNORE INTO lexicon_forms_new(form, key) VALUES(?, ?)",
                (form, key),
            )
        conn.commit()

        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            ("lexicon_pack_url", KAIKKI_URL),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            ("lexicon_pack_inserted_rows", str(inserted)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            ("lexicon_pack_seconds", str(round(time.time() - started, 2))),
        )
        conn.commit()

        conn.execute("BEGIN IMMEDIATE")
        _finalize_swap(conn)
        conn.commit()

        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a compact Wiktionary lexicon pack (Kaikki/Wiktextract) and "
            "store it into the primary offline language base."
        )
    )
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--db",
        type=Path,
        default=repo_root / "offline_language_base" / "primary.sqlite3",
        help="Path to primary.sqlite3 to update in-place.",
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=repo_root / "dev" / "tmp",
        help="Temporary directory for downloading Kaikki JSONL (gitignored).",
    )
    parser.add_argument(
        "--max-db-bytes",
        type=int,
        default=1_800_000_000,
        help="Hard cap for DB + sidecars during update (bytes).",
    )
    parser.add_argument(
        "--max-phrase-keys",
        type=int,
        default=50_000,
        help="Max number of multiword phrase keys to include.",
    )
    parser.add_argument(
        "--max-word-keys",
        type=int,
        default=200_000,
        help="Max number of single-word keys to include.",
    )
    parser.add_argument(
        "--max-translations",
        type=int,
        default=7,
        help="Max RU variants per key.",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=2_000,
        help="Commit every N inserted keys.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    limits = Limits(
        max_db_bytes=args.max_db_bytes,
        safety_margin_bytes=10_000_000,
        max_phrase_keys=args.max_phrase_keys,
        max_word_keys=args.max_word_keys,
        max_translations_per_key=args.max_translations,
        commit_every=args.commit_every,
    )
    try:
        build_lexicon_pack(db_path=args.db, tmp_dir=args.tmp_dir, limits=limits)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
