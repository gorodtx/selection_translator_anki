from __future__ import annotations

from collections import Counter
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import quote

from translate_logic.language_base.validation import (
    MIN_EXAMPLE_WORDS,
    contains_word,
    matches_translation,
    normalize_spaces,
    word_count,
)
from translate_logic.language_base.morphology_ru import ru_lemma_and_pos
from translate_logic.translation import clean_translations
from translate_logic.models import ExamplePair


def default_language_base_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    # Single source of truth: repository directory `offline_language_base/`.
    return repo_root / "offline_language_base" / "opensubtitles_lite.sqlite3"


def default_fallback_language_base_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "offline_language_base" / "fallback.sqlite3"


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
    "свой",
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

_RU_VARIANT_POS: Final[set[str]] = {
    # Prefer content words for "translation variants" from aligned corpora.
    # This avoids returning frequent verbs like "быть"/"положить" for "table".
    "NOUN",
    "ADJF",
    "ADJS",
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

        # Use immutable read-only mode: the DB is shipped as a static asset.
        # Quote the path for URI safety, but keep slashes intact.
        encoded = quote(self.db_path.as_posix(), safe="/")
        uri = f"file:{encoded}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        setattr(self._local, "conn", conn)
        return conn

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
            conn = self._connect()
            return _fetch_examples(
                conn=conn,
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
            conn = self._connect()
            return _fetch_variants(
                conn=conn,
                fts_query=query,
                limit=limit,
                fts_limit=self.fts_limit,
            )
        except sqlite3.Error:
            return ()


LanguageBaseExampleProvider = LanguageBaseProvider


def _fetch_examples(
    *,
    conn: sqlite3.Connection,
    fts_query: str,
    word: str,
    translation: str,
    limit: int,
    fts_limit: int,
) -> tuple[ExamplePair, ...]:
    def fetch_rows(row_limit: int) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT en, ru FROM examples_fts WHERE examples_fts MATCH ? LIMIT ?",
            (fts_query, row_limit),
        ).fetchall()

    # Adaptive fetch: many queries resolve quickly; avoid pulling the full
    # fts_limit into Python unless needed.
    initial = min(50, fts_limit)
    rows = fetch_rows(initial)

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

    if initial < fts_limit:
        rows = fetch_rows(fts_limit)
        selected = _select_examples(
            rows,
            word=word,
            translation=translation,
            limit=limit,
            require_translation_match=True,
            existing=selected,
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
        if not en or not ru:
            continue
        if word_count(en) < MIN_EXAMPLE_WORDS:
            continue
        if not contains_word(en, word):
            continue
        if require_translation_match and not matches_translation(ru, translation):
            continue

        pair = ExamplePair(en=en, ru=ru)
        if pair in items:
            continue
        items.append(pair)
    return tuple(items)


def _fetch_variants(
    *,
    conn: sqlite3.Connection,
    fts_query: str,
    limit: int,
    fts_limit: int,
) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT ru FROM examples_fts WHERE examples_fts MATCH ? LIMIT ?",
        (fts_query, fts_limit),
    ).fetchall()

    counter = _count_variants(rows, content_only=True)
    if not counter:
        # Some queries (e.g., modals like "might") don't have stable
        # noun/adj translations; fall back to a broader token set.
        counter = _count_variants(rows, content_only=False)

    if not counter:
        return ()
    most_common = counter.most_common()
    top_count = most_common[0][1]
    # Drop low-signal co-occurrences (e.g., "son" for "mother") while keeping
    # secondary senses ("table" -> "таблица") when they are frequent enough.
    min_count = max(2, int(top_count * 0.10))
    ranked = [candidate for candidate, count in most_common if count >= min_count]
    cleaned = clean_translations(ranked)
    return tuple(cleaned[:limit])


def _count_variants(rows: list[sqlite3.Row], *, content_only: bool) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        ru = str(row["ru"]).strip()
        if not ru:
            continue
        tokens = _tokenize_ru(ru, content_only=content_only)
        if not tokens:
            continue
        counter.update(tokens)
        counter.update(_bigrams(tokens))
    return counter


def _tokenize_ru(text: str, *, content_only: bool) -> list[str]:
    raw_tokens = [t.casefold() for t in _RU_WORD_RE.findall(text)]
    tokens: list[str] = []
    for token in raw_tokens:
        if not _is_variant_token(token):
            continue
        lemma, pos = ru_lemma_and_pos(token)
        if lemma is not None and lemma in _RU_STOPWORDS:
            continue
        if content_only and pos is not None and pos not in _RU_VARIANT_POS:
            continue
        tokens.append(lemma or token)
    return tokens


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
