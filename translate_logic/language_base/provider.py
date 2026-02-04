from __future__ import annotations

from collections import Counter
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from translate_logic.language_base.validation import (
    MIN_EXAMPLE_WORDS,
    contains_word,
    matches_translation,
    normalize_spaces,
    word_count,
)
from translate_logic.translation import clean_translations
from translate_logic.models import ExamplePair, ExampleSource


def default_language_base_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    # Single source of truth: repository directory `offline_language_base/`.
    return repo_root / "offline_language_base" / "language_base.sqlite3"


_RU_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-zА-Яа-яЁё]+(?:[-'’][A-Za-zА-Яа-яЁё]+)?"
)

_RU_STOPWORDS: Final[set[str]] = {
    # Very small set; we intentionally keep some "human noise" in the DB,
    # but translation candidates should avoid pure function words.
    "и",
    "а",
    "но",
    "да",
    "нет",
    "не",
    "ни",
    "что",
    "это",
    "то",
    "в",
    "во",
    "на",
    "у",
    "к",
    "ко",
    "за",
    "из",
    "с",
    "со",
    "от",
    "по",
    "для",
    "как",
    "я",
    "ты",
    "он",
    "она",
    "мы",
    "вы",
    "они",
    "мне",
    "тебе",
    "ему",
    "ей",
    "нам",
    "вам",
    "им",
    "меня",
    "тебя",
    "его",
    "ее",
    "её",
    "их",
    "мой",
    "моя",
    "мое",
    "моё",
    "твой",
    "твоя",
    "твое",
    "твоё",
    "наш",
    "наша",
    "наше",
    "ваш",
    "ваша",
    "ваше",
    "этот",
    "эта",
    "эти",
    "тот",
    "та",
    "те",
    "там",
    "тут",
    "здесь",
    "сейчас",
    "уже",
    "ещё",
    "еще",
    "ну",
}


def _fts_query(text: str) -> str | None:
    normalized = normalize_spaces(text)
    if not normalized:
        return None
    if " " in normalized:
        # Phrase search.
        escaped = normalized.replace('"', '""')
        return f'en:"{escaped}"'
    return f"en:{normalized}"


@dataclass(slots=True)
class LanguageBaseProvider:
    db_path: Path = default_language_base_path()
    fts_limit: int = 200

    def get_examples(
        self, *, word: str, translation: str, limit: int
    ) -> tuple[ExamplePair, ...]:
        if limit <= 0:
            return ()
        query = _fts_query(word)
        if query is None:
            return ()
        if not self.db_path.exists():
            return ()
        try:
            return _fetch_examples(
                db_path=self.db_path,
                fts_query=query,
                word=word,
                translation=translation,
                limit=limit,
                fts_limit=self.fts_limit,
            )
        except sqlite3.Error:
            return ()

    def get_variants(self, *, word: str, limit: int) -> tuple[str, ...]:
        """Best-effort translation variants from the local language base.

        We derive candidate RU variants from the aligned subtitles, preferring
        frequent content words / short phrases (1-2 tokens).
        """
        if limit <= 0:
            return ()
        query = _fts_query(word)
        if query is None:
            return ()
        if not self.db_path.exists():
            return ()
        try:
            return _fetch_variants(
                db_path=self.db_path,
                fts_query=query,
                limit=limit,
                fts_limit=self.fts_limit,
            )
        except sqlite3.Error:
            return ()


LanguageBaseExampleProvider = LanguageBaseProvider


def _fetch_examples(
    *,
    db_path: Path,
    fts_query: str,
    word: str,
    translation: str,
    limit: int,
    fts_limit: int,
) -> tuple[ExamplePair, ...]:
    # We use a separate connection per call to keep things simple and avoid
    # cross-thread issues (UI thread vs worker threads).
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT en, ru, source FROM examples_fts WHERE examples_fts MATCH ? LIMIT ?",
            (fts_query, fts_limit),
        ).fetchall()
    finally:
        conn.close()

    # 1) Prefer examples whose RU contains the requested translation.
    selected = _select_examples(
        rows,
        word=word,
        translation=translation,
        limit=limit,
        require_translation_match=True,
    )
    if len(selected) >= limit:
        return selected
    # 2) If still missing, allow RU to not contain the exact variant.
    relaxed = _select_examples(
        rows,
        word=word,
        translation=translation,
        limit=limit,
        require_translation_match=False,
        existing=selected,
    )
    return relaxed


def _select_examples(
    rows: list[sqlite3.Row],
    *,
    word: str,
    translation: str,
    limit: int,
    require_translation_match: bool,
    existing: tuple[ExamplePair, ...] = (),
) -> tuple[ExamplePair, ...]:
    items = list(existing)
    for row in rows:
        if len(items) >= limit:
            break
        en = str(row["en"]).strip()
        ru = str(row["ru"]).strip()
        raw_source = str(row["source"]).strip()
        if not en or not ru:
            continue
        if word_count(en) < MIN_EXAMPLE_WORDS:
            continue
        if not contains_word(en, word):
            continue
        if require_translation_match and not matches_translation(ru, translation):
            continue

        try:
            source = ExampleSource(raw_source)
        except ValueError:
            source = ExampleSource.LEGACY
        pair = ExamplePair(en=en, ru=ru, source=source)
        if pair in items:
            continue
        items.append(pair)
    return tuple(items)


def _fetch_variants(
    *,
    db_path: Path,
    fts_query: str,
    limit: int,
    fts_limit: int,
) -> tuple[str, ...]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ru FROM examples_fts WHERE examples_fts MATCH ? LIMIT ?",
            (fts_query, fts_limit),
        ).fetchall()
    finally:
        conn.close()

    counter: Counter[str] = Counter()
    for row in rows:
        ru = str(row["ru"]).strip()
        if not ru:
            continue
        tokens = _tokenize_ru(ru)
        if not tokens:
            continue
        counter.update(tokens)
        counter.update(_bigrams(tokens))

    if not counter:
        return ()
    ranked = [candidate for candidate, _ in counter.most_common()]
    cleaned = clean_translations(ranked)
    return tuple(cleaned[:limit])


def _tokenize_ru(text: str) -> list[str]:
    tokens = [t.casefold() for t in _RU_WORD_RE.findall(text)]
    return [t for t in tokens if _is_variant_token(t)]


def _bigrams(tokens: list[str]) -> list[str]:
    pairs: list[str] = []
    for left, right in zip(tokens, tokens[1:], strict=False):
        if left in _RU_STOPWORDS or right in _RU_STOPWORDS:
            continue
        if not _has_cyrillic(left) or not _has_cyrillic(right):
            continue
        pairs.append(f"{left} {right}")
    return pairs


def _is_variant_token(token: str) -> bool:
    if len(token) < 3:
        return False
    if token in _RU_STOPWORDS:
        return False
    # For variants we prefer Cyrillic words; latin-only tokens are usually names.
    if not _has_cyrillic(token):
        return False
    return True


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text))
