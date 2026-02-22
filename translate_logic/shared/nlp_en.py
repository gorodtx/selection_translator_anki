from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
import threading
from typing import Any


@dataclass(frozen=True, slots=True)
class TokenLemma:
    start: int
    end: int
    text: str
    lower: str
    lemma: str


_MODEL_LOCK = threading.Lock()
_MODEL: Any | None = None
_MODEL_UNAVAILABLE = False


def _cache_size() -> int:
    raw = os.environ.get("TRANSLATOR_HIGHLIGHT_CACHE_SIZE", "256")
    try:
        value = int(raw)
    except ValueError:
        value = 256
    return max(64, value)


_TOKENIZE_CACHE_SIZE = _cache_size()


def _spacy_highlight_enabled() -> bool:
    value = os.environ.get("TRANSLATOR_ENABLE_SPACY_HIGHLIGHT", "0")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_available() -> bool:
    if not _spacy_highlight_enabled():
        return False
    return _load_model() is not None


def query_lemmas(query: str) -> tuple[str, ...]:
    tokens = tokenize_lemmas(query)
    if not tokens:
        return ()
    seen: set[str] = set()
    lemmas: list[str] = []
    for token in tokens:
        if token.lemma in seen:
            continue
        seen.add(token.lemma)
        lemmas.append(token.lemma)
    return tuple(lemmas)


@lru_cache(maxsize=_TOKENIZE_CACHE_SIZE)
def tokenize_lemmas(text: str) -> tuple[TokenLemma, ...]:
    if not _spacy_highlight_enabled():
        return ()
    model = _load_model()
    if model is None:
        return ()
    if not text:
        return ()
    try:
        doc = model(text)
    except Exception:
        return ()
    tokens: list[TokenLemma] = []
    for token in doc:
        if bool(getattr(token, "is_space", False)):
            continue
        token_text = str(getattr(token, "text", ""))
        if not token_text:
            continue
        lemma_raw = str(getattr(token, "lemma_", "")).strip()
        lemma = (lemma_raw or token_text).casefold()
        start = int(getattr(token, "idx", 0))
        end = start + len(token_text)
        tokens.append(
            TokenLemma(
                start=start,
                end=end,
                text=token_text,
                lower=token_text.casefold(),
                lemma=lemma,
            )
        )
    return tuple(tokens)


def _load_model() -> Any | None:
    global _MODEL, _MODEL_UNAVAILABLE
    if _MODEL_UNAVAILABLE:
        return None
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL_UNAVAILABLE:
            return None
        if _MODEL is not None:
            return _MODEL
        try:
            import spacy
        except Exception:
            _MODEL_UNAVAILABLE = True
            return None
        try:
            _MODEL = spacy.load(
                "en_core_web_sm",
                disable=["ner", "parser", "textcat"],
            )
        except Exception:
            _MODEL_UNAVAILABLE = True
            return None
        return _MODEL
