from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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


def is_available() -> bool:
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


@lru_cache(maxsize=1024)
def tokenize_lemmas(text: str) -> tuple[TokenLemma, ...]:
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
            import spacy  # type: ignore[import-not-found]
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
