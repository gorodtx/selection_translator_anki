from __future__ import annotations

from functools import lru_cache
import re

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text))


@lru_cache(maxsize=1)
def _analyzer() -> "object":
    # Lazy import keeps CLI startup fast when morphology isn't needed.
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=8_192)
def ru_lemma(token: str) -> str | None:
    """Return a best-effort Russian lemma for a token.

    We intentionally keep this small and fast:
    - Cyrillic-only check to avoid parsing names/latin noise.
    - Cache aggressively since we call this on many short tokens.
    """
    normalized = token.strip().casefold()
    if not normalized:
        return None
    if not has_cyrillic(normalized):
        return None
    analyzer = _analyzer()
    parses = analyzer.parse(normalized)
    if not parses:
        return None
    return str(parses[0].normal_form)
