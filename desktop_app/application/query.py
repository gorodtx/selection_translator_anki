from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from translate_logic.models import QueryLimit
from translate_logic.shared.text import normalize_lookup_text

ENGLISH_RE = re.compile(r"[A-Za-z]")


class QueryError(Enum):
    NO_TEXT = "no_text"
    NO_ENGLISH = "no_english"
    UNSUPPORTED_LANGUAGE = "unsupported_language"


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    display_text: str | None
    network_text: str | None
    lookup_text: str | None
    error: QueryError | None


def prepare_query(raw_text: str, source_lang: str, target_lang: str) -> QueryOutcome:
    if not raw_text or not raw_text.strip():
        return QueryOutcome(
            display_text=None,
            network_text=None,
            lookup_text=None,
            error=QueryError.NO_TEXT,
        )
    display_text = raw_text[: QueryLimit.MAX_CHARS.value].strip()
    network_text = display_text
    lookup_text = normalize_lookup_text(display_text)
    if not lookup_text or not ENGLISH_RE.search(lookup_text):
        return QueryOutcome(
            display_text=display_text,
            network_text=None,
            lookup_text=None,
            error=QueryError.NO_ENGLISH,
        )
    if source_lang != "en" or target_lang != "ru":
        return QueryOutcome(
            display_text=display_text,
            network_text=None,
            lookup_text=None,
            error=QueryError.UNSUPPORTED_LANGUAGE,
        )
    return QueryOutcome(
        display_text=display_text,
        network_text=network_text,
        lookup_text=lookup_text,
        error=None,
    )
