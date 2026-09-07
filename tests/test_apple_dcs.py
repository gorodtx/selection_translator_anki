"""Structured Dictionary Services markup to :class:`LexicalInfo`.

Fixtures are synthetic: they reproduce the Oxford Russian Dictionary's markup structure
with invented content, so no dictionary text is redistributed. The behaviours they pin
down were read off real entries on macOS 26 (``bank`` is three homographs, ``look up`` is
an anchored phrasal-verb section inside ``look``, ``went`` resolves to ``go``).

The last test drives the real sidecar and skips wherever it is not built.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from typing import cast

import pytest

from translate_logic.domain.models import LexicalInfo
from translate_logic.infrastructure.providers.apple_dcs import (
    DcsRecord,
    lexical_from_records,
    records_from_json,
    strip_stress,
    translation_candidates,
)

_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<html xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rng"><head/><body>'
)
_TAIL = "</body></html>"
OXFORD = "Oxford Russian Dictionary"


def _entry(title: str, body: str, *, entry_id: str = "e_test") -> str:
    return (
        f'{_HEAD}<d:entry id="{entry_id}" d:title="{title}" class="entry" lang="ru">'
        f"{body}</d:entry>{_TAIL}"
    )


def _headword(
    word: str, *, homograph: str = "", br: str = "tɛst", am: str = "tɛst"
) -> str:
    marker = f'<span class="gp ty_hom tg_hw">{homograph}</span>' if homograph else ""
    return (
        '<span class="hwg x_xh0">'
        f'<span d:dhw="1" class="hw">{word} {marker}</span>'
        '<span dialect="BrE" class="prx"><span class="gp tg_prx"> | </span>'
        f'<span dialect="BrE" class="ph">{br}<d:prn/></span></span>'
        '<span dialect="AmE" class="prx">'
        f'<span dialect="AmE" class="ph">{am}<d:prn/></span></span>'
        "</span>"
    )


def _indicator(text: str) -> str:
    return (
        f'<span class="ind"><span class="gp tg_ind">(</span>{text}'
        '<span class="gp tg_ind">) </span></span>'
    )


def _example(en: str, ru: str) -> str:
    return (
        '<span class="exg x_xd2 hasSn"><span class="x_xdh"><span class="sn">▸ </span>'
        f'<span class="ex">{en}</span></span>'
        f'<span class="trg x_xd3"><span class="trans">{ru}</span></span></span>'
    )


def _aspect_pair(impf: str, pf: str) -> str:
    def form(word: str, tag: str) -> str:
        return (
            '<span class="tfrm"><span class="gp tg_tfrm">(</span>'
            f'{word}<span class="tgr"><span class="gp tg_tgr"> (</span>{tag}'
            '<span class="gp tg_tgr">)</span></span><span class="gp tg_tfrm">)</span></span>'
        )

    return (
        f'<span class="trans">{form(impf, "impf")}'
        f'<span class="gp tg_tfrm">/ </span>{form(pf, "pf")}</span>'
    )


def _sense(number: str, indicator: str, translations: str, examples: str = "") -> str:
    return (
        '<span class="semb x_xd1 hasSn">'
        f'<span class="gp x_xdh sn ty_label tg_semb">{number} </span>'
        f'<span class="trg x_xd2">{_indicator(indicator) if indicator else ""}'
        f"{translations}</span>{examples}</span>"
    )


NOUN_ENTRY = _entry(
    "brook",
    _headword("brook", homograph="1", br="brʊk", am="brʊk")
    + '<span class="gramb x_xd0"><span class="ps x_xdh">noun <d:pos/></span>'
    + _sense(
        "1",
        "small stream",
        '<span class="trans">руче́й<span class="gp tg_tr">, </span></span>'
        '<span class="trans">пото́к</span>',
        _example("a brook of clear water", "руче́й с чи́стой водо́й"),
    )
    + _sense("2", "figurative", '<span class="trans">струя́</span>')
    + "</span>"
    + '<span class="gramb x_xd0"><span class="ps x_xdh">transitive verb <d:pos/></span>'
    + '<span class="semb x_xd1 hasSn"><span class="gp x_xdh sn ty_label tg_semb">1 </span>'
    + '<span class="trgg x_xd2"><span class="fld"><span class="gp tg_fld">(</span>Aviation'
    + '<span class="gp tg_fld">)</span></span><span class="trg">'
    + _aspect_pair("терпе́ть", "потерпе́ть")
    + "</span></span></span></span>",
)

SECOND_HOMOGRAPH = _entry(
    "brook",
    _headword("brook", homograph="2", br="brʊk", am="brʊk")
    + '<span class="gramb x_xd0"><span class="ps x_xdh">noun <d:pos/></span>'
    + _sense("1", "Finance", '<span class="trans">вклад</span>')
    + "</span>",
    entry_id="e_test2",
)

PHRASAL_ENTRY = _entry(
    "look",
    _headword("look", br="lʊk", am="lʊk")
    + '<span class="gramb x_xd0"><span class="ps x_xdh">noun <d:pos/></span>'
    + _sense("1", "", '<span class="trans">взгляд</span>')
    + "</span>"
    + '<span class="pvb x_xo0">'
    + '<span id="e_test_20" class="pvsec x_xo1"><span class="pvg x_xoh"><span class="pv">'
    + '<span class="rf"><span class="gp tg_rf">look </span></span>up</span></span>'
    + '<span class="gramb x_xo2"><span class="ps x_xdh">transitive verb</span>'
    + '<span class="semb x_xo3"><span class="trg x_xo4">'
    + _indicator("visit")
    + _aspect_pair("навеща́ть", "навести́ть")
    + "</span>"
    + _example("look up old friends", "навести́ть ста́рых друзе́й")
    + "</span></span></span>"
    + '<span id="e_test_21" class="pvsec x_xo1"><span class="pvg x_xoh"><span class="pv">'
    + '<span class="rf"><span class="gp tg_rf">look </span></span>upon</span></span>'
    + '<span class="gramb x_xo2"><span class="ps x_xdh">transitive verb</span>'
    + '<span class="semb x_xo3"><span class="trg x_xo4"><span class="trans">счита́ть</span>'
    + "</span></span></span></span>"
    + "</span>",
)

INFLECTED_ENTRY = _entry(
    "go",
    _headword("go", br="ɡəʊ", am="ɡoʊ")
    + '<span class="gramb x_xd0"><span class="ps x_xdh">intransitive verb <d:pos/></span>'
    + '<span class="semb x_xd1 hasSn"><span class="gp x_xdh sn ty_label tg_semb">1 </span>'
    + '<span class="trg x_xd2">'
    + _indicator("on foot")
    + _aspect_pair("ходи́ть", "пойти́")
    + "</span></span></span>",
)

CROSS_REF_ENTRY = _entry(
    "children",
    _headword("children")
    + '<span class="gramb x_xd0"><span class="semb x_xd1">'
    + '<span class="gr x_xd2">pl of</span>'
    + '<span class="xrg x_xd2"><span class="xr">'
    + '<a href="x-dictionary:r:e_1" title="child">child</a></span></span>'
    + "</span></span>",
)

GOVERNED_ENTRY = _entry(
    "encounter",
    _headword("encounter")
    + '<span class="gramb x_xd0"><span class="ps x_xdh">transitive verb <d:pos/></span>'
    + _sense(
        "1",
        "meet",
        _aspect_pair("ната́лкиваться на + a", "натолкну́ться на + a")
        + '<span class="trans">следи́ть глаза́ми за + i</span>',
    )
    + "</span>",
)

NOISY_ENTRY = _entry(
    "dabble",
    _headword("dabble")
    + '<span class="gramb x_xd0"><span class="ps x_xdh">transitive verb <d:pos/></span>'
    + _sense(
        "1",
        "in water",
        '<span class="trans">меша́ть, по-<span class="gp tg_tr">, </span></span>'
        '<span class="trans">осм|а́тривать, -отре́ть</span>'
        '<span class="trans">води́ть по воде́ рука́ми и́ли нога́ми до́лгое вре́мя</span>',
    )
    + "</span>",
)


def _record(
    markup: str, headword: str, *, title: str = "", anchor: str = ""
) -> dict[str, object]:
    return {
        "dictionary": OXFORD,
        "headword": headword,
        "title": title or None,
        "anchor": anchor or None,
        "markup": markup,
    }


def _card(payload: object, *, query: str) -> LexicalInfo:
    info = lexical_from_records(records_from_json(payload), query=query)
    assert info is not None
    return info


# --------------------------------------------------------------------- records_from_json


def test_records_read_the_result_object_or_a_bare_list() -> None:
    raw = [_record(NOUN_ENTRY, "brook")]
    from_object = records_from_json({"records": raw, "elapsed_ms": 1.2})
    from_list = records_from_json(raw)
    assert from_object == from_list
    assert from_object == [
        DcsRecord(
            dictionary=OXFORD, headword="brook", title="", anchor="", markup=NOUN_ENTRY
        )
    ]


def test_records_normalise_missing_title_and_anchor() -> None:
    records = records_from_json([_record(NOUN_ENTRY, "brook")])
    assert records[0].title == ""
    assert records[0].anchor == ""


def test_records_skip_unusable_payloads() -> None:
    assert records_from_json(None) == []
    assert records_from_json("records") == []
    assert records_from_json({"records": "nope"}) == []
    assert records_from_json([{"headword": "brook"}]) == []  # no markup
    assert records_from_json([{"markup": NOUN_ENTRY}]) == []  # no headword
    assert records_from_json([42, {"markup": NOUN_ENTRY, "headword": "brook"}]) == [
        DcsRecord(
            dictionary="", headword="brook", title="", anchor="", markup=NOUN_ENTRY
        )
    ]


# --------------------------------------------------------------------- lexical_from_records


def test_card_carries_headword_ipa_and_pos_blocks() -> None:
    info = _card([_record(NOUN_ENTRY, "brook")], query="brook")
    assert info.headword == "brook"
    assert info.ipa_uk == "brʊk"
    assert info.ipa_us == "brʊk"
    assert info.source == "apple_dictionary"
    assert [entry.pos for entry in info.entries] == ["noun", "transitive verb"]


def test_senses_keep_dictionary_numbering_labels_and_examples() -> None:
    info = _card([_record(NOUN_ENTRY, "brook")], query="brook")
    noun = info.entries[0]
    assert [sense.index for sense in noun.senses] == [1, 2]
    first = noun.senses[0]
    assert first.label == "small stream"
    assert first.translation == "руче́й, пото́к"
    assert [(pair.en, pair.ru) for pair in first.examples] == [
        ("a brook of clear water", "руче́й с чи́стой водо́й")
    ]
    assert noun.senses[1].translation == "струя́"


def test_aspect_pairs_and_subject_labels_survive() -> None:
    info = _card([_record(NOUN_ENTRY, "brook")], query="brook")
    verb = info.entries[1].senses[0]
    assert verb.translation == "терпе́ть (impf) / потерпе́ть (pf)"
    assert verb.label == "Aviation"


def test_homographs_merge_into_one_card_with_superscripts() -> None:
    info = _card(
        [_record(NOUN_ENTRY, "brook"), _record(SECOND_HOMOGRAPH, "brook")],
        query="brook",
    )
    assert [entry.pos for entry in info.entries] == [
        "noun¹",
        "transitive verb¹",
        "noun²",
    ]
    assert info.entries[2].senses[0].translation == "вклад"
    assert "вклад" in translation_candidates(info)


def test_single_record_keeps_a_plain_part_of_speech() -> None:
    info = _card([_record(NOUN_ENTRY, "brook")], query="brook")
    assert all("¹" not in entry.pos for entry in info.entries)


def test_anchor_narrows_a_phrasal_verb_to_its_own_section() -> None:
    info = _card(
        [
            _record(
                PHRASAL_ENTRY,
                "look up",
                title="look",
                anchor="xpointer(//*[@id='e_test_20'])",
            )
        ],
        query="look up",
    )
    assert info.headword == "look up"
    assert [entry.pos for entry in info.entries] == ["transitive verb"]
    sense = info.entries[0].senses[0]
    assert sense.translation == "навеща́ть (impf) / навести́ть (pf)"
    assert sense.label == "visit"
    assert sense.examples[0].en == "look up old friends"
    # The parent entry's own senses and the sibling phrasal verb stay out.
    assert "взгляд" not in translation_candidates(info)
    assert "считать" not in translation_candidates(info)


def test_without_an_anchor_the_whole_entry_including_phrasal_verbs_is_kept() -> None:
    info = _card([_record(PHRASAL_ENTRY, "look")], query="look")
    assert [entry.pos for entry in info.entries] == [
        "noun",
        "look up · transitive verb",
        "look upon · transitive verb",
    ]
    assert "взгляд" in translation_candidates(info)


def test_an_anchor_that_matches_nothing_falls_back_to_the_whole_entry() -> None:
    info = _card(
        [_record(PHRASAL_ENTRY, "look", anchor="xpointer(//*[@id='e_missing'])")],
        query="look",
    )
    assert info.entries[0].pos == "noun"


def test_inflected_form_keeps_its_headword_and_borrows_the_lemma_senses() -> None:
    info = _card([_record(INFLECTED_ENTRY, "went", title="go")], query="went")
    assert info.headword == "went"
    assert info.ipa_uk == "ɡəʊ"
    assert info.entries[0].senses[0].translation == "ходи́ть (impf) / пойти́ (pf)"
    assert translation_candidates(info)[:2] == ["ходить", "пойти"]


def test_cross_reference_entry_renders_an_arrow() -> None:
    info = _card([_record(CROSS_REF_ENTRY, "children")], query="children")
    assert info.entries[0].senses[0].translation == "pl of → child"
    assert translation_candidates(info) == []


def test_no_usable_record_yields_no_card() -> None:
    assert lexical_from_records([], query="brook") is None
    broken = [DcsRecord(OXFORD, "brook", "", "", "<html><body>nope</body></html>")]
    assert lexical_from_records(broken, query="brook") is None
    malformed = [DcsRecord(OXFORD, "brook", "", "", "<not xml")]
    assert lexical_from_records(malformed, query="brook") is None


# --------------------------------------------------------------------- candidates


def test_candidates_are_deduplicated_and_stress_free() -> None:
    info = _card(
        [_record(NOUN_ENTRY, "brook"), _record(SECOND_HOMOGRAPH, "brook")],
        query="brook",
    )
    assert translation_candidates(info) == [
        "ручей",
        "поток",
        "струя",
        "терпеть",
        "потерпеть",
        "вклад",
    ]


def test_candidates_drop_notes_that_are_not_translations() -> None:
    info = _card([_record(NOISY_ENTRY, "dabble")], query="dabble")
    candidates = translation_candidates(info)
    # Oxford writes an aspect pair as "меша́ть, по-" and a shared stem as
    # "осм|а́тривать, -отре́ть". The intact stem is a translation; the dangling affix that
    # follows it is not. The eight-word gloss is a definition, not a gloss to put on a card.
    assert candidates == ["мешать", "осматривать"]


def test_candidates_drop_the_case_a_verb_governs() -> None:
    """ "наталкиваться на + a" is a translation with a grammar note, not a reject.

    The note is a latin letter, so before it was stripped the whole candidate failed the
    latin check and entries like "come across" produced nothing at all.
    """
    info = _card([_record(GOVERNED_ENTRY, "encounter")], query="encounter")
    assert translation_candidates(info) == [
        "наталкиваться на",
        "натолкнуться на",
        "следить глазами за",
    ]


def test_candidates_keep_a_plus_that_is_not_a_case_marker() -> None:
    info = _card(
        [
            _record(
                _entry(
                    "plus",
                    _headword("plus")
                    + '<span class="gramb x_xd0"><span class="ps x_xdh">noun</span>'
                    + _sense("1", "", '<span class="trans">плюс</span>')
                    + "</span>",
                ),
                "plus",
            )
        ],
        query="plus",
    )
    assert translation_candidates(info) == ["плюс"]


def test_candidates_keep_a_qualifier_whole() -> None:
    """ "настоя́щее (вре́мя)" must not lose its closing bracket.

    Stripping brackets from both ends of a fragment ate the qualifier's closing one and
    put "настоящее (время" on the card.
    """
    body = (
        _headword("present")
        + '<span class="gramb x_xd0"><span class="ps x_xdh">noun</span>'
        + _sense("1", "", '<span class="trans">настоя́щее (вре́мя)</span>')
        + "</span>"
    )
    info = _card([_record(_entry("present", body), "present")], query="present")
    assert translation_candidates(info) == ["настоящее (время)"]


def test_candidates_unwrap_a_fully_bracketed_fragment() -> None:
    body = (
        _headword("aside")
        + '<span class="gramb x_xd0"><span class="ps x_xdh">adverb</span>'
        + _sense("1", "", '<span class="trans">(в сто́рону)</span>')
        + "</span>"
    )
    info = _card([_record(_entry("aside", body), "aside")], query="aside")
    assert translation_candidates(info) == ["в сторону"]


def test_strip_stress_keeps_other_diacritics() -> None:
    assert strip_stress("руче́й") == "ручей"
    assert strip_stress("ёлка") == "ёлка"
    assert strip_stress("plain") == "plain"


# --------------------------------------------------------------------- live sidecar


def _sidecar() -> Path | None:
    repo = Path(__file__).resolve().parents[1]
    binary = (
        repo / "macos" / "AppleLangHelper" / ".build" / "release" / "apple-lang-helper"
    )
    return binary if binary.exists() and os.access(binary, os.X_OK) else None


def _dictionary_names(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    listed = cast(dict[str, object], payload).get("dictionaries", [])
    if not isinstance(listed, list):
        return []
    names: list[str] = []
    for item in cast(list[object], listed):
        if isinstance(item, dict):
            name = cast(dict[str, object], item).get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _has_russian_dictionary(payload: object) -> bool:
    return any(
        "Russian" in name or "Русско" in name for name in _dictionary_names(payload)
    )


@pytest.mark.skipif(
    sys.platform != "darwin", reason="Dictionary Services is macOS only"
)
def test_live_sidecar_records_parse_into_a_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the real Swift sidecar's markup through the real parser.

    Skips unless the sidecar is built and an English-Russian dictionary is enabled in
    Dictionary.app, so a machine without either still runs a green suite.
    """
    monkeypatch.delenv("TRANSLATOR_DISABLE_APPLE_ENGINES", raising=False)
    binary = _sidecar()
    if binary is None:
        pytest.skip("sidecar not built (macos/AppleLangHelper: swift build -c release)")

    async def scenario() -> tuple[object, object]:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            stdin = process.stdin
            stdout = process.stdout
            assert stdin is not None and stdout is not None

            async def call(payload: str) -> object:
                import json

                stdin.write(payload.encode("utf-8") + b"\n")
                await stdin.drain()
                line = await asyncio.wait_for(stdout.readline(), 10.0)
                message: object = json.loads(line)
                assert isinstance(message, dict), message
                body = cast(dict[str, object], message)
                assert body["ok"] is True, body
                return body["result"]

            dictionaries = await call('{"id":"1","op":"dictionaries"}')
            # The define below names a dictionary, so it errors outright where
            # none is enabled — the skip has to be decided before that call,
            # not after. A CI runner has no Russian dictionary at all.
            if not _has_russian_dictionary(dictionaries):
                return dictionaries, None
            bank = await call(
                '{"id":"2","op":"define","term":"bank","dictionary":"Oxford Russian"}'
            )
            return dictionaries, bank
        finally:
            process.kill()
            await process.wait()

    dictionaries, bank = asyncio.run(scenario())
    if bank is None:
        pytest.skip(
            f"no English-Russian dictionary enabled: {_dictionary_names(dictionaries)}"
        )

    records = records_from_json(bank)
    assert records, bank
    assert all(record.markup.startswith("<?xml") for record in records)
    info = lexical_from_records(records, query="bank")
    assert info is not None
    assert info.headword == "bank"
    assert info.entries
    candidates = translation_candidates(info)
    assert candidates, info
    assert all(candidate == strip_stress(candidate) for candidate in candidates)
