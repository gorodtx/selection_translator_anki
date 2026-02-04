from __future__ import annotations

from functools import lru_cache
import re

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")

_POS_NONE = None


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


@lru_cache(maxsize=8_192)
def ru_lemma_and_pos(token: str) -> tuple[str | None, str | None]:
    """Return (lemma, POS) for a Russian token.

    POS is a pymorphy tag like NOUN/ADJF/VERB/INFN/etc.
    """
    normalized = token.strip().casefold()
    if not normalized:
        return None, _POS_NONE
    if not has_cyrillic(normalized):
        return None, _POS_NONE
    analyzer = _analyzer()
    parses = analyzer.parse(normalized)
    if not parses:
        return None, _POS_NONE
    best = parses[0]
    pos = getattr(best.tag, "POS", None)
    return str(best.normal_form), str(pos) if pos is not None else _POS_NONE
