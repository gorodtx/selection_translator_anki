from __future__ import annotations

from dataclasses import dataclass
import html
import re

from translate_logic.shared import nlp_en
from translate_logic.shared.text import normalize_whitespace

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


@dataclass(frozen=True, slots=True)
class HighlightSpec:
    query_raw: str
    phrase_patterns: tuple[str, ...]
    token_literals: tuple[str, ...]
    token_lemmas: tuple[str, ...]


def build_highlight_spec(query: str) -> HighlightSpec:
    normalized = normalize_whitespace(query)
    if not normalized:
        return HighlightSpec(
            query_raw="",
            phrase_patterns=(),
            token_literals=(),
            token_lemmas=(),
        )
    token_bases = tuple(dict.fromkeys(_TOKEN_RE.findall(normalized.casefold())))
    token_forms = _expand_forms(token_bases)
    token_literals = tuple(dict.fromkeys([*token_bases, *token_forms]))
    lemmas = nlp_en.query_lemmas(normalized)
    return HighlightSpec(
        query_raw=normalized,
        phrase_patterns=(normalized,),
        token_literals=token_literals,
        token_lemmas=lemmas,
    )


def _expand_forms(tokens: tuple[str, ...]) -> tuple[str, ...]:
    forms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) < 3:
            continue
        for candidate in _heuristic_variants(token):
            if candidate in seen:
                continue
            seen.add(candidate)
            forms.append(candidate)
    return tuple(forms)


def _heuristic_variants(token: str) -> tuple[str, ...]:
    variants: set[str] = {token}
    if token.endswith("y") and len(token) > 3:
        stem = token[:-1]
        variants.add(f"{stem}ies")
        variants.add(f"{stem}ied")
    else:
        variants.add(f"{token}s")
        variants.add(f"{token}es")
        variants.add(f"{token}ed")
    if token.endswith("e") and len(token) > 3:
        variants.add(f"{token[:-1]}ing")
    else:
        variants.add(f"{token}ing")
    if _is_cvc(token):
        last = token[-1]
        variants.add(f"{token}{last}ed")
        variants.add(f"{token}{last}ing")
    return tuple(variants)


def _is_cvc(token: str) -> bool:
    if len(token) < 3:
        return False
    vowels = "aeiou"
    a, b, c = token[-3], token[-2], token[-1]
    return (a not in vowels) and (b in vowels) and (c not in vowels)


def highlight_to_pango_markup(text: str, spec: HighlightSpec) -> str:
    ranges = _match_ranges(text, spec)
    return _render_marked(
        text,
        ranges,
        open_mark='<span background="#fff4a8" foreground="#1f2328">',
        close_mark="</span>",
        escape_output=True,
    )


def highlight_to_html_mark(
    text: str,
    spec: HighlightSpec,
    class_name: str = "hl",
) -> str:
    ranges = _match_ranges(text, spec)
    class_escaped = html.escape(class_name, quote=True)
    return _render_marked(
        text,
        ranges,
        open_mark=f'<mark class="{class_escaped}">',
        close_mark="</mark>",
        escape_output=True,
    )


def highlight_to_markdown(text: str, spec: HighlightSpec) -> str:
    ranges = _match_ranges(text, spec)
    return _render_marked(
        text,
        ranges,
        open_mark="**",
        close_mark="**",
        escape_output=False,
    )


def _match_ranges(text: str, spec: HighlightSpec) -> tuple[tuple[int, int], ...]:
    if not text or not spec.query_raw:
        return ()
    phrase_ranges = _find_phrase_ranges(text, spec.phrase_patterns)
    token_ranges = _find_token_ranges(text, spec)
    merged = _merge_ranges([*phrase_ranges, *token_ranges])
    return tuple(merged)


def _find_phrase_ranges(
    text: str,
    phrases: tuple[str, ...],
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for phrase in phrases:
        if not phrase:
            continue
        escaped = re.escape(phrase)
        if " " in phrase:
            pattern = re.compile(escaped, flags=re.IGNORECASE)
        else:
            pattern = re.compile(rf"(?<![A-Za-z]){escaped}(?![A-Za-z])", re.IGNORECASE)
        for match in pattern.finditer(text):
            ranges.append((match.start(), match.end()))
    return ranges


def _find_token_ranges(text: str, spec: HighlightSpec) -> list[tuple[int, int]]:
    if not text:
        return []
    literal_set = set(spec.token_literals)
    lemma_set = set(spec.token_lemmas)
    if not literal_set and not lemma_set:
        return []

    tokens = nlp_en.tokenize_lemmas(text)
    if tokens:
        ranges: list[tuple[int, int]] = []
        for token in tokens:
            if token.lower in literal_set or token.lemma in lemma_set:
                ranges.append((token.start, token.end))
        return ranges

    ranges = []
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).casefold()
        if token in literal_set:
            ranges.append((match.start(), match.end()))
    return ranges


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    valid = [(start, end) for start, end in ranges if start >= 0 and end > start]
    if not valid:
        return []
    valid.sort(key=lambda item: (item[0], item[1]))
    merged: list[tuple[int, int]] = []
    current_start, current_end = valid[0]
    for start, end in valid[1:]:
        if start > current_end:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
            continue
        current_end = max(current_end, end)
    merged.append((current_start, current_end))
    return merged


def _render_marked(
    text: str,
    ranges: tuple[tuple[int, int], ...],
    *,
    open_mark: str,
    close_mark: str,
    escape_output: bool,
) -> str:
    if not text:
        return ""
    if not ranges:
        return _escape(text) if escape_output else text
    parts: list[str] = []
    cursor = 0
    for start, end in ranges:
        if start > cursor:
            segment = text[cursor:start]
            parts.append(_escape(segment) if escape_output else segment)
        marked = text[start:end]
        rendered = _escape(marked) if escape_output else marked
        parts.append(f"{open_mark}{rendered}{close_mark}")
        cursor = end
    if cursor < len(text):
        tail = text[cursor:]
        parts.append(_escape(tail) if escape_output else tail)
    return "".join(parts)


def _escape(value: str) -> str:
    return html.escape(value, quote=False)
