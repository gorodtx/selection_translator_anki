from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from translate_logic.models import QueryLimit

ENGLISH_RE = re.compile(r"[A-Za-z]")
QUERY_CLEAN_RE = re.compile(r"[^A-Za-z'-]+")


class QueryError(Enum):
    NO_TEXT = "no_text"
    NO_ENGLISH = "no_english"
    UNSUPPORTED_LANGUAGE = "unsupported_language"


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    display_text: str | None
    query_text: str | None
    error: QueryError | None


def normalize_query_text(value: str) -> str:
    cleaned = QUERY_CLEAN_RE.sub(" ", value)
    return " ".join(cleaned.split())


def prepare_query(raw_text: str, source_lang: str, target_lang: str) -> QueryOutcome:
    if not raw_text or not raw_text.strip():
        return QueryOutcome(
            display_text=None, query_text=None, error=QueryError.NO_TEXT
        )
    display_text = raw_text[: QueryLimit.MAX_CHARS.value]
    query_text = normalize_query_text(display_text)
    if not query_text or not ENGLISH_RE.search(query_text):
        return QueryOutcome(
            display_text=display_text,
            query_text=None,
            error=QueryError.NO_ENGLISH,
        )
    if source_lang != "en" or target_lang != "ru":
        return QueryOutcome(
            display_text=display_text,
            query_text=None,
            error=QueryError.UNSUPPORTED_LANGUAGE,
        )
    return QueryOutcome(display_text=display_text, query_text=query_text, error=None)
