"""Structured Dictionary Services entries: XHTML markup to :class:`LexicalInfo`.

The Swift sidecar's ``define`` op returns one record per dictionary entry, each carrying
the entry's own XHTML (``DCSRecordCopyData``). That markup is what the flat
``DCSCopyTextDefinition`` string throws away, and the difference is large:

* **Homographs stay separate.** ``bank`` is three records (river bank, financial bank,
  tier of oars); the flat text only ever shows the first.
* **Phrasal verbs are addressable.** ``look up`` comes back as one record whose headword is
  ``look up`` and whose anchor points at a ``pvsec`` section inside the ``look`` entry.
  Without the anchor the caller gets the whole ``look`` article, 36 senses of it.
* **Inflected forms resolve.** ``went`` is a record whose title is ``go``; the headword the
  user asked for is preserved while the senses come from the ``go`` entry.

Everything here is stdlib-only and platform independent, so it is exercised on Linux too.

Markup vocabulary (class names used by the Oxford Russian Dictionary bundle):

``hwg``/``hw``/``ty_hom``
    headword group, headword, homograph number
``prx``/``ph``
    pronunciation group (``dialect`` attribute BrE/AmE) and its IPA
``gramb``/``ps``
    part-of-speech block and its label
``semb``/``sn``
    sense block and sense number
``trgg``/``trg``/``trans``/``tfrm``/``tgr``
    translation groups, a translation, an aspect form, a grammar tag (pf/impf/det/indet)
``ind``/``fld``/``lev``/``reg``
    indicator (gloss), subject field, level and register labels
``gr``
    grammar note (``pl of``, ``with preps``)
``exg``/``ex``
    example group and its English side; the group's ``trans`` is the Russian side
``xrg``/``xr``
    cross reference (``color = colour``, ``children: pl of child``)
``infg``/``inf``
    inflections
``pvb``/``pvsec``/``pvg``/``pv``
    phrasal-verb block, section, group and the phrase itself
``gp``
    typographic glue (brackets, bars, commas); ``rf`` is the headword inside an example
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import re
from typing import Final, cast
import unicodedata
import xml.etree.ElementTree as ET

from translate_logic.domain.models import (
    ExamplePair,
    LexicalEntry,
    LexicalInfo,
    LexicalSense,
)
from translate_logic.shared.text import count_words, normalize_whitespace

__all__ = [
    "DcsRecord",
    "lexical_from_records",
    "records_from_json",
    "translation_candidates",
]

DCS_SOURCE: Final[str] = "apple_dictionary"

_D_NS: Final[str] = "{http://www.apple.com/DTDs/DictionaryService-1.0.rng}"
_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(r"@id='([^']+)'")
_CYRILLIC_RE: Final[re.Pattern[str]] = re.compile(r"[А-Яа-яЁё]")
_LATIN_OR_OPERATOR_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z+=]")
_ASPECT_RE: Final[re.Pattern[str]] = re.compile(r"\((?:impf|pf|det|indet|iter)\.?\)")
_LATIN_PAREN_RE: Final[re.Pattern[str]] = re.compile(r"\((?:[^()]*[A-Za-z][^()]*)\)")
# Oxford appends the case a verb governs as a latin letter: "наталкиваться на + a"
# (accusative), "следить за + i" (instrumental). It is a grammar note on an otherwise
# ordinary translation, so it has to go before the latin-letter check rejects the lot.
_CASE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"\s*\+\s*[a-z]{1,2}\b\.?")
_COMBINING_ACUTE: Final[str] = "́"
_LABEL_CLASSES: Final[tuple[str, ...]] = ("ind", "fld", "lev", "reg")
_MAX_CANDIDATE_WORDS: Final[int] = 5
_SUPERSCRIPTS: Final[str] = "⁰¹²³⁴⁵⁶⁷⁸⁹"


@dataclass(frozen=True, slots=True)
class DcsRecord:
    """One ``define`` record. ``title`` and ``anchor`` are empty when absent."""

    dictionary: str
    headword: str
    title: str
    anchor: str
    markup: str


def records_from_json(payload: object) -> list[DcsRecord]:
    """Read ``result["records"]`` (or the whole ``result``) into records.

    Anything that is not a well-formed record object is skipped rather than raising: the
    sidecar is a separate process and a partial answer is still worth showing.
    """
    items: object = payload
    if isinstance(payload, dict):
        items = cast(dict[str, object], payload).get("records", [])
    if not isinstance(items, list):
        return []
    records: list[DcsRecord] = []
    for entry in cast(list[object], items):
        if not isinstance(entry, dict):
            continue
        item = cast(dict[str, object], entry)
        markup = _as_text(item.get("markup"))
        headword = _as_text(item.get("headword"))
        if not markup or not headword:
            continue
        records.append(
            DcsRecord(
                dictionary=_as_text(item.get("dictionary")),
                headword=headword,
                title=_as_text(item.get("title")),
                anchor=_as_text(item.get("anchor")),
                markup=markup,
            )
        )
    return records


def lexical_from_records(
    records: Sequence[DcsRecord], *, query: str
) -> LexicalInfo | None:
    """Merge every record for one lookup into a single card.

    Homographs become consecutive part-of-speech blocks, disambiguated by the dictionary's
    own superscript. A record whose anchor points at a phrasal-verb section contributes
    only that section. The headword is the one the dictionary matched, so ``look up`` stays
    ``look up`` and ``went`` stays ``went`` even though its senses come from ``go``.
    """
    del query  # matching is the caller's policy; every record here already matched
    entries: list[LexicalEntry] = []
    headword = ""
    ipa_uk = ""
    ipa_us = ""
    multiple = len(records) > 1

    for record in records:
        parsed = _parse_entry(record.markup, anchor=record.anchor)
        if parsed is None:
            continue
        if not headword:
            headword = record.headword or parsed.headword
        if not ipa_uk:
            ipa_uk = parsed.pronunciations.get("BrE", "")
        if not ipa_us:
            ipa_us = parsed.pronunciations.get("AmE", "")
        suffix = _homograph_suffix(parsed.homograph) if multiple else ""
        entries.extend(_entries_from(parsed, suffix=suffix))

    if not headword or not entries:
        return None
    return LexicalInfo(
        headword=headword,
        ipa_uk=ipa_uk,
        ipa_us=ipa_us,
        entries=tuple(entries),
        source=DCS_SOURCE,
    )


def translation_candidates(info: LexicalInfo) -> list[str]:
    """Short Russian glosses from a card, in dictionary order, without duplicates.

    Aspect tags, stress marks, stem separators and English glosses are stripped; anything
    still carrying Latin letters, a dangling affix (``по-``, ``-ать``) or more than five
    words is a dictionary note rather than a translation and is dropped.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in info.entries:
        for sense in entry.senses:
            for candidate in _split_candidates(sense.translation):
                key = candidate.casefold()
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(candidate)
    return ordered


# --------------------------------------------------------------------- candidates


def _unwrap(fragment: str) -> str:
    """Drop brackets that wrap a whole fragment, keeping an ordinary qualifier intact."""
    if fragment.startswith("(") and fragment.endswith(")"):
        return fragment[1:-1].strip()
    return fragment


def _split_candidates(translation: str) -> Iterator[str]:
    if not translation:
        return
    cleaned = translation.replace(_COMBINING_ACUTE, "").replace("|", "")
    cleaned = _ASPECT_RE.sub("", cleaned)
    cleaned = _LATIN_PAREN_RE.sub("", cleaned)
    cleaned = _CASE_MARKER_RE.sub("", cleaned)
    for piece in re.split(r"[/,;]", cleaned):
        candidate = _unwrap(piece.strip())
        if candidate.count("(") != candidate.count(")"):
            # A qualifier the split cut in half; the halves are not translations.
            continue
        tokens = candidate.split()
        # "по-" / "-ать" are inflection notes glued to the previous form, never a
        # translation on their own, so the whole fragment goes.
        if any(token.startswith("-") or token.endswith("-") for token in tokens):
            continue
        candidate = normalize_whitespace(" ".join(tokens))
        if not candidate or not _CYRILLIC_RE.search(candidate):
            continue
        if _LATIN_OR_OPERATOR_RE.search(candidate):
            continue
        if count_words(candidate) > _MAX_CANDIDATE_WORDS:
            continue
        yield candidate


# --------------------------------------------------------------------- parsed shapes


@dataclass(frozen=True, slots=True)
class _Translation:
    text: str
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Sense:
    number: str
    labels: tuple[str, ...]
    translations: tuple[_Translation, ...]
    examples: tuple[ExamplePair, ...]
    grammar: tuple[str, ...]
    cross_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Block:
    pos: str
    senses: tuple[_Sense, ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    headword: str
    homograph: int | None
    pronunciations: dict[str, str]
    blocks: tuple[_Block, ...]
    phrasal_verbs: tuple[tuple[str, tuple[_Block, ...]], ...]
    matched_phrase: str


# --------------------------------------------------------------------- XML helpers


def _as_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _has(element: ET.Element, *names: str) -> bool:
    classes = set(element.attrib.get("class", "").split())
    return any(name in classes for name in names)


def _tidy(text: str) -> str:
    collapsed = normalize_whitespace(text)
    collapsed = re.sub(r"\(\s+", "(", collapsed)
    collapsed = re.sub(r"\s+\)", ")", collapsed)
    collapsed = re.sub(r"\s+([,;:.!?])", r"\1", collapsed)
    collapsed = re.sub(r"\s*/\s*", "/", collapsed)
    return collapsed.strip(" ,;:")


def _text(element: ET.Element, *, skip: tuple[str, ...] = ()) -> str:
    def walk(node: ET.Element) -> Iterator[str]:
        if node.text:
            yield node.text
        for child in node:
            if not (skip and _has(child, *skip)):
                yield from walk(child)
            if child.tail:
                yield child.tail

    return _tidy("".join(walk(element)))


def _descendants(
    element: ET.Element, *names: str, stop_at: tuple[str, ...] = ()
) -> Iterator[ET.Element]:
    """Document-order descendants carrying any class in *names*.

    A match is yielded but not descended into; a ``stop_at`` subtree is skipped whole.
    """
    for child in element:
        if _has(child, *names):
            yield child
            continue
        if stop_at and _has(child, *stop_at):
            continue
        yield from _descendants(child, *names, stop_at=stop_at)


def _clean_label(text: str) -> str:
    return text.strip().lstrip("(").rstrip(")").strip(" :,;")


def _labels_of(element: ET.Element, *, stop_at: tuple[str, ...]) -> tuple[str, ...]:
    labels = (
        _clean_label(_text(node))
        for node in _descendants(element, *_LABEL_CLASSES, stop_at=stop_at)
    )
    return tuple(label for label in labels if label)


def _grammar_of(element: ET.Element, *, stop_at: tuple[str, ...]) -> tuple[str, ...]:
    notes = (_text(node) for node in _descendants(element, "gr", stop_at=stop_at))
    return tuple(note for note in notes if note)


def _cross_refs_of(element: ET.Element, *, stop_at: tuple[str, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for group in _descendants(element, "xrg", stop_at=stop_at):
        for reference in _descendants(group, "xr"):
            anchor = next(
                (node for node in reference.iter() if _local(node.tag) == "a"), None
            )
            title = anchor.attrib.get("title", "") if anchor is not None else ""
            text = title or _text(reference)
            if text:
                refs.append(text)
    return tuple(refs)


def _translation_text(node: ET.Element) -> str:
    forms = list(_descendants(node, "tfrm"))
    if forms:
        parts = [_text(form, skip=("tg_tfrm",)) for form in forms]
        text = " / ".join(part for part in parts if part)
    else:
        text = _text(node, skip=("tg_tr",))
    # Oxford writes shared stems as "осм|а́тривать, -отре́ть".
    return text.replace("|", "")


def _translations_in(
    container: ET.Element, *, shared: tuple[str, ...], stop_at: tuple[str, ...]
) -> Iterator[_Translation]:
    for group in _descendants(container, "trg", stop_at=stop_at):
        labels = shared + _labels_of(group, stop_at=("trans", "exg"))
        for node in _descendants(group, "trans", stop_at=("exg",)):
            text = _translation_text(node)
            if text:
                yield _Translation(text=text, labels=labels)


def _translation_groups(container: ET.Element) -> Iterator[_Translation]:
    """Translations of *container* itself, never those inside its examples.

    A ``trgg`` wraps several ``trg`` groups behind one subject label, and that label
    applies to every translation inside it.
    """
    for outer in _descendants(container, "trgg", stop_at=("exg",)):
        shared = _labels_of(outer, stop_at=("trg", "exg"))
        yield from _translations_in(outer, shared=shared, stop_at=("exg",))
    yield from _translations_in(container, shared=(), stop_at=("exg", "trgg"))
    for node in _descendants(container, "trans", stop_at=("exg", "trg", "trgg")):
        text = _translation_text(node)
        if text:
            yield _Translation(text=text, labels=())


def _example(group: ET.Element) -> ExamplePair | None:
    english = next(_descendants(group, "ex"), None)
    if english is None:
        return None
    source = _text(english)
    if not source:
        return None
    parts: list[str] = []
    for translation in _translation_groups(group):
        prefix = f"({', '.join(translation.labels)}) " if translation.labels else ""
        parts.append(f"{prefix}{translation.text}")
    return ExamplePair(en=source, ru="; ".join(parts))


def _sense(block: ET.Element) -> _Sense:
    number = ""
    for marker in _descendants(block, "sn", stop_at=("exg", "trg", "trgg")):
        text = _text(marker).rstrip(":").strip()
        if text and text != "▸":
            number = text
            break
    examples = tuple(
        pair
        for pair in (_example(group) for group in _descendants(block, "exg"))
        if pair is not None
    )
    return _Sense(
        number=number,
        labels=_labels_of(block, stop_at=("trg", "trgg", "exg")),
        translations=tuple(_translation_groups(block)),
        examples=examples,
        grammar=_grammar_of(block, stop_at=("trg", "trgg", "exg")),
        cross_refs=_cross_refs_of(block, stop_at=("exg",)),
    )


def _block(gramb: ET.Element) -> _Block:
    label = next(_descendants(gramb, "ps", stop_at=("semb",)), None)
    if label is None:
        # Blocks like go's "with preps" carry a grammar note where the part of speech
        # would normally be.
        label = next(_descendants(gramb, "gr", stop_at=("semb",)), None)
    pos = _text(label) if label is not None else ""
    senses = list(_descendants(gramb, "semb"))
    if senses:
        return _Block(pos=pos, senses=tuple(_sense(sense) for sense in senses))
    if any(_descendants(gramb, "trans", "exg", "xrg")):
        return _Block(pos=pos, senses=(_sense(gramb),))
    return _Block(pos=pos, senses=())


def _phrasal_verb(section: ET.Element) -> tuple[str, tuple[_Block, ...]]:
    phrase_node = next(_descendants(section, "pv"), None)
    phrase = _text(phrase_node) if phrase_node is not None else ""
    blocks = tuple(_block(gramb) for gramb in _descendants(section, "gramb"))
    if not blocks and any(_descendants(section, "trans", "exg")):
        blocks = (_Block(pos="", senses=(_sense(section),)),)
    return phrase, blocks


def _anchor_id(anchor: str) -> str:
    match = _ANCHOR_RE.search(anchor)
    return match.group(1) if match else ""


def _parse_entry(markup: str, *, anchor: str = "") -> _Entry | None:
    try:
        root = ET.fromstring(markup)
    except ET.ParseError:
        return None
    entry = next(
        (node for node in root.iter() if _local(node.tag) == "entry"),
        None,
    )
    if entry is None:
        return None

    headword = entry.attrib.get(f"{_D_NS}title", "") or entry.attrib.get("title", "")
    homograph: int | None = None
    pronunciations: dict[str, str] = {}
    group = next(_descendants(entry, "hwg"), None)
    if group is not None:
        node = next(_descendants(group, "hw"), None)
        if node is not None:
            headword = _text(node, skip=("ty_hom",)) or headword
            marker = next(_descendants(node, "ty_hom"), None)
            if marker is not None and _text(marker).isdigit():
                homograph = int(_text(marker))
        for pronunciation in _descendants(group, "prx"):
            dialect = pronunciation.attrib.get("dialect", "")
            ipa = next(_descendants(pronunciation, "ph"), None)
            if dialect and ipa is not None:
                pronunciations.setdefault(dialect, _text(ipa))

    target = _anchor_id(anchor)
    if target:
        node = next(
            (item for item in entry.iter() if item.attrib.get("id") == target), None
        )
        if node is not None and _has(node, "pvsec"):
            phrase, blocks = _phrasal_verb(node)
            return _Entry(
                headword=headword,
                homograph=homograph,
                pronunciations=pronunciations,
                blocks=(),
                phrasal_verbs=((phrase, blocks),),
                matched_phrase=phrase,
            )

    blocks = tuple(
        _block(gramb)
        for gramb in _descendants(entry, "gramb", stop_at=("pvsec", "pvb"))
    )
    if not blocks:
        loose = list(_descendants(entry, "semb", stop_at=("pvsec", "pvb")))
        if loose:
            blocks = (_Block(pos="", senses=tuple(_sense(item) for item in loose)),)
    phrasal = tuple(_phrasal_verb(node) for node in _descendants(entry, "pvsec"))
    return _Entry(
        headword=headword,
        homograph=homograph,
        pronunciations=pronunciations,
        blocks=blocks,
        phrasal_verbs=phrasal,
        matched_phrase="",
    )


# --------------------------------------------------------------------- assembly


def _homograph_suffix(homograph: int | None) -> str:
    if homograph is None or not 0 <= homograph < len(_SUPERSCRIPTS):
        return ""
    return _SUPERSCRIPTS[homograph]


def _entries_from(entry: _Entry, *, suffix: str) -> list[LexicalEntry]:
    if entry.matched_phrase:
        blocks = [block for _, pv_blocks in entry.phrasal_verbs for block in pv_blocks]
        return _lexical_entries(blocks, prefix="", suffix=suffix)
    result = _lexical_entries(list(entry.blocks), prefix="", suffix=suffix)
    for phrase, phrase_blocks in entry.phrasal_verbs:
        result.extend(_lexical_entries(list(phrase_blocks), prefix=phrase, suffix=""))
    return result


def _lexical_entries(
    blocks: Sequence[_Block], *, prefix: str, suffix: str
) -> list[LexicalEntry]:
    entries: list[LexicalEntry] = []
    for block in blocks:
        senses = tuple(
            sense
            for sense in (
                _lexical_sense(index, item)
                for index, item in enumerate(block.senses, start=1)
            )
            if sense is not None
        )
        if not senses:
            continue
        pos = f"{block.pos}{suffix}" if block.pos else suffix
        if prefix:
            pos = f"{prefix} · {pos}".strip(" ·")
        entries.append(LexicalEntry(pos=pos, senses=senses))
    return entries


def _lexical_sense(index: int, sense: _Sense) -> LexicalSense | None:
    labels: list[str] = list(sense.labels)
    for translation in sense.translations:
        for label in translation.labels:
            if label not in labels:
                labels.append(label)
    text = ", ".join(translation.text for translation in sense.translations)
    if sense.grammar:
        text = f"{text} {' '.join(sense.grammar)}".strip()
    if sense.cross_refs:
        text = f"{text} → {', '.join(sense.cross_refs)}".strip()
    if not text and not sense.examples:
        return None
    return LexicalSense(
        index=int(sense.number) if sense.number.isdigit() else index,
        label="; ".join(labels),
        translation=text,
        examples=sense.examples,
    )


def strip_stress(text: str) -> str:
    """Drop the combining acute used as a stress mark, keeping other diacritics."""
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", decomposed.replace(_COMBINING_ACUTE, ""))
