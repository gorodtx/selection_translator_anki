from __future__ import annotations

from collections import Counter
import json
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
    normalize_spaces,
    word_count,
)
from translate_logic.language_base.morphology_ru import ru_lemma_pos_grammemes
from translate_logic.translation import clean_translations
from translate_logic.models import ExamplePair


def default_language_base_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    # Single source of truth: repository directory `offline_language_base/`.
    return repo_root / "offline_language_base" / "primary.sqlite3"


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
    # Particles/conjunctions that heavily pollute corpus-derived variants.
    "бы",
    "если",
    # Relative / demonstrative / low-signal words that frequently pollute
    # corpus-derived "variants" for modals and function words.
    "который",
    "какой",
    "самый",
    "такой",
    "весь",
    "любой",
    "каждый",
    "некоторый",
    "прочий",
    "всякий",
    "сам",
    # Pymorphy sometimes produces this lemma from "нибудь"; it's never a
    # meaningful translation variant on its own.
    "нибыть",
}

_RU_VARIANT_POS: Final[set[str]] = {
    # Prefer content words for "translation variants" from aligned corpora.
    # This avoids returning frequent verbs like "быть"/"положить" for "table".
    "NOUN",
    "ADJF",
    "ADJS",
}

_RU_VERB_POS: Final[frozenset[str]] = frozenset({"VERB", "INFN"})

_RU_EXCLUDE_GRAMMEMES: Final[frozenset[str]] = frozenset(
    {
        # Proper names / geography / organizations tend to leak into variants
        # from aligned corpora and look like "мэри" / "бостон".
        "Name",
        "Surn",
        "Patr",
        "Geox",
        "Orgn",
    }
)

_RU_NOISE_VERBS: Final[frozenset[str]] = frozenset(
    {
        "быть",
        "мочь",
        "знать",
        "иметь",
        "делать",
        "сделать",
    }
)

# High-frequency content lemmas that often dominate phrase lookups and produce
# useless "variants" (e.g. "by the way" -> "человек"). We only apply this to
# multi-word queries where we want idiom/phrasal-verb-like translations.
_RU_PHRASE_NOISE: Final[frozenset[str]] = frozenset(
    {
        "быть",
        "мочь",
        "человек",
        "люди",
        "год",
        "день",
        "время",
        "жизнь",
        "дело",
        "мир",
        "друг",
        "другой",
        "новый",
        "старый",
        "хороший",
        "плохой",
        "должный",
        "место",
        "работа",
        "проблема",
    }
)

_EN_MODAL_KEYS: Final[frozenset[str]] = frozenset(
    {
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
)

_RU_MODAL_VARIANTS: Final[frozenset[str]] = frozenset(
    {
        # Modal/auxiliary equivalents that appear frequently in aligned corpora.
        "возможно",
        "вероятно",
        "пожалуй",
        "можно",
        "нельзя",
        "нужно",
        "надо",
        "следует",
        "стоит",
        "должен",
        "должна",
        "должны",
    }
)


def _fts_query(text: str) -> str | None:
    normalized = normalize_spaces(text)
    if not normalized:
        return None
    # FTS5 query syntax is strict: many punctuation characters are operators.
    # If it's not a simple ASCII word, use a phrase query.
    if re.fullmatch(r"[A-Za-z0-9]+", normalized):
        return f"en:{normalized}"
    escaped = normalized.replace('"', '""')
    return f'en:"{escaped}"'


def _is_phrase_key(key: str) -> bool:
    normalized = normalize_spaces(key)
    # "Phrase" here means multi-word only. Contractions like "can't" are
    # treated as single-token keys and handled via the lexicon.
    return " " in normalized


def _ru_pos_weight(pos: str | None) -> int:
    """Prefer verbs/adverbs for phrase lookups (give up, by the way, etc.)."""
    if pos is None:
        return 1
    if pos in {"VERB", "INFN"}:
        return 4
    if pos in {"ADVB"}:
        return 4
    if pos in {"CONJ", "PRCL", "INTJ"}:
        return 3
    if pos in {"NOUN"}:
        return 2
    if pos in {"ADJF", "ADJS"}:
        return 2
    return 1


def _normalize_key(text: str) -> str:
    # Normalize apostrophes so user input ("'") matches corpora ("’") and vice versa.
    return normalize_spaces(text).replace("’", "'").casefold()


def _resolve_lexicon_key(conn: sqlite3.Connection, word: str) -> str:
    normalized = _normalize_key(word)
    if not normalized:
        return normalized
    try:
        row = conn.execute(
            "SELECT key FROM lexicon_forms WHERE form = ? LIMIT 1",
            (normalized,),
        ).fetchone()
    except sqlite3.Error:
        return normalized
    if row is None:
        return normalized
    return str(row[0])


def _fetch_lexicon_variants(
    conn: sqlite3.Connection, *, key: str, limit: int
) -> list[str]:
    if not key or limit <= 0:
        return []
    try:
        row = conn.execute(
            "SELECT ru_json FROM lexicon WHERE key = ? LIMIT 1",
            (key,),
        ).fetchone()
    except sqlite3.Error:
        return []
    if row is None:
        return []
    raw = row[0]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = normalize_spaces(item)
        if not cleaned:
            continue
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


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

    def get_examples(self, *, word: str, limit: int) -> tuple[ExamplePair, ...]:
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
            normalized = _normalize_key(word)

            # Modal verbs and contractions are best handled via the aligned corpus:
            # Wiktionary/Kaikki is often missing good RU equivalents for these,
            # and generic co-occurrence extraction is very noisy.
            if normalized in _EN_MODAL_KEYS:
                corpus_query = _fts_query(normalized) or query
                corpus = _fetch_modal_variants(
                    conn=conn,
                    fts_query=corpus_query,
                    limit=limit,
                    fts_limit=self.fts_limit,
                )
                if corpus:
                    return tuple(clean_translations(list(corpus))[:limit])
            if "'" in normalized and not _is_phrase_key(normalized):
                corpus_query = _fts_query(normalized) or query
                corpus = _fetch_contraction_variants(
                    conn=conn,
                    fts_query=corpus_query,
                    limit=limit,
                    fts_limit=self.fts_limit,
                )
                if corpus:
                    return tuple(clean_translations(list(corpus))[:limit])

            key = _resolve_lexicon_key(conn, normalized)
            lexicon = _fetch_lexicon_variants(conn, key=key, limit=limit)
            # For multi-word queries and contractions, prefer lexicon results
            # whenever they exist: corpus-derived phrase variants are much
            # noisier for idioms/phrasal verbs and for "can't"/"won't".
            if lexicon:
                if _is_phrase_key(key) or "'" in key or "-" in key:
                    return tuple(clean_translations(lexicon)[:limit])
                # For common single-token keys (modals/function words), don't
                # mix in noisy corpus co-occurrences once lexicon is "good
                # enough".
                if re.fullmatch(r"[A-Za-z0-9]+", key) and len(lexicon) >= min(limit, 3):
                    return tuple(clean_translations(lexicon)[:limit])

            # Derive extra candidates from the aligned corpora (best-effort).
            corpus_query = _fts_query(key) or query
            if _is_phrase_key(key):
                corpus = _fetch_phrase_variants(
                    conn=conn,
                    fts_query=corpus_query,
                    limit=limit,
                    fts_limit=self.fts_limit,
                )
            else:
                corpus = _fetch_variants(
                    conn=conn,
                    fts_query=corpus_query,
                    limit=limit,
                    fts_limit=self.fts_limit,
                )

            merged = clean_translations(list(lexicon) + list(corpus))
            return tuple(merged[:limit])
        except sqlite3.Error:
            return ()


LanguageBaseExampleProvider = LanguageBaseProvider


def _fetch_examples(
    *,
    conn: sqlite3.Connection,
    fts_query: str,
    word: str,
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

    selected = _select_examples(rows, word=word, limit=limit)
    if len(selected) >= limit:
        return selected[:limit]

    if initial < fts_limit:
        rows = fetch_rows(fts_limit)
        selected = _select_examples(rows, word=word, limit=limit)
    return selected[:limit]


_PUNCT_RE: Final[re.Pattern[str]] = re.compile(r"[\"'“”«»()\\[\\]{}<>—–-]")
_END_PUNCT: Final[tuple[str, ...]] = (".", "?", "!")


def _sentence_score(en: str) -> int:
    """Cheap ranking heuristic for picking more 'dictionary-like' sentences."""
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
    # Penalize heavy punctuation/noise.
    letters = sum(1 for ch in stripped if ch.isalpha())
    punct = len(_PUNCT_RE.findall(stripped))
    if letters > 0 and punct > 0:
        ratio = punct / letters
        if ratio > 0.20:
            score -= 3
        elif ratio > 0.12:
            score -= 1
    return score


def _select_examples(
    rows: list[sqlite3.Row],
    *,
    word: str,
    limit: int,
) -> tuple[ExamplePair, ...]:
    # Collect candidates then sort by our heuristic (FTS rank is not enough).
    candidates: list[tuple[int, ExamplePair]] = []
    seen: set[ExamplePair] = set()
    for row in rows:
        en = str(row["en"]).strip()
        ru = str(row["ru"]).strip()
        if not en or not ru:
            continue
        if word_count(en) < MIN_EXAMPLE_WORDS:
            continue
        if not contains_word(en, word):
            continue
        pair = ExamplePair(en=en, ru=ru)
        if pair in seen:
            continue
        seen.add(pair)
        candidates.append((_sentence_score(en), pair))

    candidates.sort(key=lambda item: item[0], reverse=True)
    out: list[ExamplePair] = []
    for _, pair in candidates:
        if len(out) >= limit:
            break
        out.append(pair)
    return tuple(out)


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
    verb_counter = _count_variants(rows, content_only=False, verbs_only=True)
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
    min_count = max(2, int(top_count * 0.08))
    # Prefer singular nouns when counts are comparable: this helps avoid
    # noisy co-occurrences like "переговоры" for "table".
    ranked_scored: list[tuple[int, str]] = []
    for candidate, count in most_common:
        if count < min_count:
            continue
        score = count * 10
        lemma, pos, grammemes = ru_lemma_pos_grammemes(candidate)
        if pos == "NOUN" and grammemes and "plur" in grammemes:
            score -= 2
        ranked_scored.append((score, candidate))
    ranked_scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [candidate for _, candidate in ranked_scored]

    # If verb translations exist, make sure at least one surfaces for verb-ish
    # lookups (e.g. "befall" -> "постигать"), even if nouns dominate.
    if verb_counter:
        verb_top = verb_counter.most_common(1)[0][1]
        # Only mix verbs in when they are prominent in the aligned corpus subset.
        if verb_top >= max(2, int(top_count * 0.35)):
            for candidate, _ in verb_counter.most_common(10):
                if candidate in _RU_NOISE_VERBS:
                    continue
                if candidate in ranked:
                    continue
                ranked.insert(min(2, len(ranked)), candidate)
    cleaned = clean_translations(ranked)
    return tuple(cleaned[:limit])


def _fetch_modal_variants(
    *,
    conn: sqlite3.Connection,
    fts_query: str,
    limit: int,
    fts_limit: int,
) -> tuple[str, ...]:
    """Best-effort modal/auxiliary variants from aligned corpora.

    Function words (may/might/can/should...) tend to produce very noisy
    co-occurrence lists. Here we extract a small, human-friendly set of
    Russian modal equivalents ("может быть", "возможно", "можно", ...).
    """
    rows = conn.execute(
        "SELECT ru FROM examples_fts WHERE examples_fts MATCH ? LIMIT ?",
        (fts_query, fts_limit),
    ).fetchall()

    scores: Counter[str] = Counter()
    for row in rows:
        ru = str(row["ru"]).strip()
        if not ru:
            continue
        tokens = [t.casefold() for t in _RU_WORD_RE.findall(ru)]
        if not tokens:
            continue

        for i, tok in enumerate(tokens):
            if not _has_cyrillic(tok):
                continue
            if tok in _RU_STOPWORDS:
                continue
            lemma, _, _ = ru_lemma_pos_grammemes(tok)
            if lemma is None:
                continue
            if lemma in _RU_STOPWORDS:
                continue

            if lemma in _RU_MODAL_VARIANTS:
                scores[lemma] += 8

            if lemma == "мочь":
                # "может быть" / "быть может"
                if i + 1 < len(tokens):
                    next_lemma, _, _ = ru_lemma_pos_grammemes(tokens[i + 1])
                    if next_lemma == "быть":
                        scores["может быть"] += 14
                if i > 0:
                    prev_lemma, _, _ = ru_lemma_pos_grammemes(tokens[i - 1])
                    if prev_lemma == "быть":
                        scores["быть может"] += 12

                # Conditional: "мог бы ..." (normalize to the canonical form).
                if i + 1 < len(tokens) and tokens[i + 1] == "бы":
                    scores["мог бы"] += 13

                # Present/ability: normalize all forms to "может".
                scores["может"] += 4

    if not scores:
        return ()
    most_common = scores.most_common()
    cleaned = clean_translations([candidate for candidate, _ in most_common])
    return tuple(cleaned[:limit])


def _fetch_contraction_variants(
    *,
    conn: sqlite3.Connection,
    fts_query: str,
    limit: int,
    fts_limit: int,
) -> tuple[str, ...]:
    """Variants for contractions (can't/won't/isn't...) from aligned corpora."""
    rows = conn.execute(
        "SELECT ru FROM examples_fts WHERE examples_fts MATCH ? LIMIT ?",
        (fts_query, fts_limit),
    ).fetchall()

    scores: Counter[str] = Counter()
    for row in rows:
        ru = str(row["ru"]).strip()
        if not ru:
            continue
        tokens = [t.casefold() for t in _RU_WORD_RE.findall(ru)]
        if not tokens:
            continue

        for i, tok in enumerate(tokens):
            if tok == "нельзя":
                scores["нельзя"] += 12
                continue

            # Prefer explicit negation patterns: "не могу", "не будет", etc.
            if tok != "не":
                continue
            if i + 1 >= len(tokens):
                continue
            nxt = tokens[i + 1]
            if not _has_cyrillic(nxt):
                continue
            lemma, pos, _ = ru_lemma_pos_grammemes(nxt)
            if lemma is None or lemma in _RU_STOPWORDS:
                continue
            if pos not in _RU_VERB_POS and lemma not in {"мочь", "быть"}:
                continue

            # Keep the original surface form ("не могу" / "не может").
            phrase = f"не {nxt}"
            if lemma == "мочь":
                scores[phrase] += 14
            elif lemma == "быть":
                scores[phrase] += 10
            else:
                scores[phrase] += 6

    if not scores:
        return ()
    most_common = scores.most_common()
    cleaned = clean_translations([candidate for candidate, _ in most_common])
    return tuple(cleaned[:limit])


def _fetch_phrase_variants(
    *,
    conn: sqlite3.Connection,
    fts_query: str,
    limit: int,
    fts_limit: int,
) -> tuple[str, ...]:
    """Variant derivation for multi-word queries (idioms/phrasal verbs).

    Unlike single-word lookups, phrase translations are often best represented
    by a short RU verb/adverb or a stable RU phrase near the sentence start.
    """
    rows = conn.execute(
        "SELECT en, ru FROM examples_fts WHERE examples_fts MATCH ? LIMIT ?",
        (fts_query, fts_limit),
    ).fetchall()

    scores: Counter[str] = Counter()
    for row in rows:
        ru = str(row["ru"]).strip()
        if not ru:
            continue
        surface = [t.casefold() for t in _RU_WORD_RE.findall(ru)]
        if not surface:
            continue

        # 1) Prefer short RU phrases from the sentence prefix: "кстати", "между прочим".
        prefix = surface[:5]
        for n in (1, 2, 3):
            for i in range(0, max(0, len(prefix) - n + 1)):
                chunk = prefix[i : i + n]
                if not chunk:
                    continue
                # Skip pure stopword chunks.
                if all(tok in _RU_STOPWORDS for tok in chunk):
                    continue
                if n == 1:
                    lemma, pos, grammemes = ru_lemma_pos_grammemes(chunk[0])
                    if grammemes and not grammemes.isdisjoint(_RU_EXCLUDE_GRAMMEMES):
                        continue
                    if (
                        lemma is None
                        or lemma in _RU_STOPWORDS
                        or lemma in _RU_PHRASE_NOISE
                    ):
                        continue
                    # Avoid returning standalone prepositions ("между") as variants.
                    if pos in {"PREP"}:
                        continue
                value = " ".join(chunk)
                if not any(_has_cyrillic(tok) for tok in chunk):
                    continue
                weight = 3 if n == 1 else 5 if n == 2 else 6
                scores[value] += weight

        # 2) Add weighted lemma unigrams across the full sentence to surface verbs/adverbs.
        for tok in surface:
            if not _has_cyrillic(tok):
                continue
            lemma, pos, grammemes = ru_lemma_pos_grammemes(tok)
            if grammemes and not grammemes.isdisjoint(_RU_EXCLUDE_GRAMMEMES):
                continue
            if lemma is None:
                continue
            if lemma in _RU_STOPWORDS:
                continue
            if lemma in _RU_PHRASE_NOISE:
                continue
            if pos in {"CONJ", "PRCL"}:
                continue
            scores[lemma] += _ru_pos_weight(pos)

    if not scores:
        return ()
    most_common = scores.most_common()
    cleaned = clean_translations([candidate for candidate, _ in most_common])
    return tuple(cleaned[:limit])


def _count_variants(
    rows: list[sqlite3.Row],
    *,
    content_only: bool,
    verbs_only: bool = False,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        ru = str(row["ru"]).strip()
        if not ru:
            continue
        tokens = _tokenize_ru(ru, content_only=content_only, verbs_only=verbs_only)
        if not tokens:
            continue
        counter.update(tokens)
    return counter


def _tokenize_ru(text: str, *, content_only: bool, verbs_only: bool) -> list[str]:
    raw_tokens = [t.casefold() for t in _RU_WORD_RE.findall(text)]
    tokens: list[str] = []
    for token in raw_tokens:
        if not _is_variant_token(token):
            continue
        lemma, pos, grammemes = ru_lemma_pos_grammemes(token)
        if grammemes and not grammemes.isdisjoint(_RU_EXCLUDE_GRAMMEMES):
            continue
        if lemma is not None and lemma in _RU_STOPWORDS:
            continue
        if verbs_only and pos is not None and pos not in _RU_VERB_POS:
            continue
        if content_only and pos is not None and pos not in _RU_VARIANT_POS:
            continue
        tokens.append(lemma or token)
    return tokens


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
