from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat
import sys
import textwrap
from typing import cast

import pytest

from translate_logic.infrastructure.providers import apple
from translate_logic.models import (
    Example,
    FieldValue,
    LexicalEntry,
    LexicalInfo,
    LexicalSense,
    TranslationResult,
)

BANK_RAW = (
    "bank 1 | BrE baŋk, AmE bæŋk | noun 1 (of river) бе́рег 2 (under-water shelf) "
    "ба́нка 3 (of snow) зано́с, сугро́б ▸ bank of clouds гряда́ облако́в▸ bank of fog "
    "полоса́ тума́на▸ banks of earth земляны́е валы́ 4 (embankment) на́сыпь transitive "
    "verb 1: ▸ bank (up) a fire подде́рж|ивать, -а́ть ого́нь 2 (Aviation) (крени́ть "
    "(impf))/ (накрени́ть (pf)) intransitive verb 1 (also bank up) (of snow etc.) "
    "(образо́вывать (impf) зано́сы)/ (образова́ть (pf) зано́сы) 2 (Aviation) "
    "(накреня́ться (impf))/ (накрени́ться (pf)) "
)
LOOK_RAW = (
    "look | BrE lʊk, AmE lʊk | noun 1 (glance) взгляд ▸ he gave me a look он бро́сил "
    "взгляд (or взгляну́л) на меня́▸ there were angry looks from the crowd толпа́ "
    "гляде́ла с негодова́нием▸ give sb a black look зло́бно посмотре́ть/взгляну́ть (pf) "
    "на кого́-н.▸ may I have, take a look at your paper? позво́льте просмотре́ть ва́шу "
    "газе́ту 2: ▸ have, take a look at (examine) осм|а́тривать, -отре́ть рассм|а́тривать, "
    "-отре́ть▸ the doctor had a good look at his throat до́ктор внима́тельно посмотре́л "
    "его́ го́рло"
)
OXFORD_RU = "Oxford Russian Dictionary - Русско-Английский • Англо-Русский"

# Structured entry markup, the shape ``DCSRecordCopyData`` returns. Content is
# invented; only the class names and nesting match the real dictionary.
BANK_MARKUP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<html xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rng"><head/><body>'
    '<d:entry id="e_bank" d:title="bank" class="entry" lang="ru">'
    '<span class="hwg x_xh0"><span d:dhw="1" class="hw">bank </span>'
    '<span dialect="BrE" class="prx"><span class="ph">baŋk<d:prn/></span></span>'
    '<span dialect="AmE" class="prx"><span class="ph">bæŋk<d:prn/></span></span></span>'
    '<span class="gramb x_xd0"><span class="ps x_xdh">noun <d:pos/></span>'
    '<span class="semb x_xd1 hasSn"><span class="gp x_xdh sn ty_label tg_semb">1 </span>'
    '<span class="trg x_xd2"><span class="ind"><span class="gp tg_ind">(</span>of river'
    '<span class="gp tg_ind">) </span></span><span class="trans">бе́рег</span></span>'
    '<span class="exg x_xd2 hasSn"><span class="x_xdh"><span class="sn">▸ </span>'
    '<span class="ex">bank of fog</span></span><span class="trg x_xd3">'
    '<span class="trans">полоса́ тума́на</span></span></span></span></span>'
    "</d:entry></body></html>"
)


def test_parse_oxford_russian_extracts_ipa_pos_senses_and_examples() -> None:
    info = apple.parse_oxford_russian(BANK_RAW)

    assert info is not None
    assert info.headword == "bank"
    assert (info.ipa_uk, info.ipa_us) == ("baŋk", "bæŋk")
    assert [entry.pos for entry in info.entries] == [
        "noun",
        "transitive verb",
        "intransitive verb",
    ]
    noun = info.entries[0]
    assert [sense.index for sense in noun.senses] == [1, 2, 3, 4]
    assert noun.senses[0].label == "of river"
    assert noun.senses[0].translation == "бе́рег"
    assert noun.senses[2].translation == "зано́с, сугро́б"
    assert [pair.en for pair in noun.senses[2].examples] == [
        "bank of clouds",
        "bank of fog",
        "banks of earth",
    ]
    assert noun.senses[2].examples[0].ru == "гряда́ облако́в"
    transitive = info.entries[1]
    assert transitive.senses[0].translation == ""
    assert transitive.senses[0].examples[0].en == "bank (up) a fire"
    assert transitive.senses[1].label == "Aviation"


def test_definition_candidates_strip_stress_and_grammar_noise() -> None:
    info = apple.parse_oxford_russian(BANK_RAW)
    assert info is not None
    definition = apple.AppleDefinition(lexical=info, dictionary=OXFORD_RU, raw=BANK_RAW)

    candidates = definition.candidates()

    assert candidates[:5] == ["берег", "банка", "занос", "сугроб", "насыпь"]
    assert "кренить" in candidates
    assert all("́" not in candidate for candidate in candidates)
    assert definition.matches("bank")
    assert definition.matches("Bank ")
    assert not definition.matches("banks")
    assert definition.example_sentences()[0] == "bank of clouds"


def test_parse_oxford_russian_handles_phrasal_lookup_returning_headword() -> None:
    info = apple.parse_oxford_russian(LOOK_RAW)

    assert info is not None
    assert info.headword == "look"
    noun = info.entries[0]
    assert noun.senses[0].label == "glance"
    assert noun.senses[0].translation == "взгляд"
    assert len(noun.senses[0].examples) == 4
    assert noun.senses[0].examples[0].en == "he gave me a look"
    assert noun.senses[0].examples[0].ru == "он бро́сил взгляд (or взгляну́л) на меня́"
    assert noun.senses[1].examples[0].en == "have, take a look at"
    definition = apple.AppleDefinition(lexical=info, dictionary=OXFORD_RU, raw=LOOK_RAW)
    assert not definition.matches("look up")


@pytest.mark.parametrize("raw", ["", "no separator here", "word | "])
def test_parse_oxford_russian_rejects_garbage(raw: str) -> None:
    assert apple.parse_oxford_russian(raw) is None


def test_parse_oxford_russian_single_sense_entry_without_numbers() -> None:
    raw = (
        "serendipity | BrE ˌsɛr(ə)nˈdɪpɪti, AmE ˌsɛrənˈdɪpədi | noun счастли́вая "
        "спосо́бность де́лать неожи́данные откры́тия "
    )

    info = apple.parse_oxford_russian(raw)

    assert info is not None
    assert info.ipa_uk == "ˌsɛr(ə)nˈdɪpɪti"
    assert [entry.pos for entry in info.entries] == ["noun"]
    assert info.entries[0].senses[0].translation == (
        "счастли́вая спосо́бность де́лать неожи́данные откры́тия"
    )
    definition = apple.AppleDefinition(lexical=info, dictionary=OXFORD_RU, raw=raw)
    assert definition.candidates() == [
        "счастливая способность делать неожиданные открытия"
    ]


def test_translation_candidates_drop_grammar_fragments() -> None:
    raw = (
        "look | BrE lʊk, AmE lʊk | verb 1 (use eyes) смотре́ть, по- в глаза кому-н. "
        "2 (appear) выглядеть + i, eye смотреть, каза́ться"
    )
    info = apple.parse_oxford_russian(raw)
    assert info is not None
    definition = apple.AppleDefinition(lexical=info, dictionary=OXFORD_RU, raw=raw)

    # "по-" is a dangling prefix and goes. "выглядеть + i" is a translation carrying
    # the case it governs, so only the marker goes and the verb stays; dropping it
    # whole is what left "come across" with no candidates at all.
    assert definition.candidates() == ["смотреть", "выглядеть", "казаться"]


def test_translation_candidates_keep_verbs_that_govern_a_case() -> None:
    """ "наталкиваться на + a" is a translation with a grammar note, not a reject.

    The note is a latin letter, and the cleaner rejects latin letters, so entries whose
    senses all govern a case used to produce nothing: "come across" had no candidates
    at all despite three aspect pairs.
    """
    raw = (
        "come across | BrE kʌm, AmE kəm | verb 1 (encounter) ната́лкиваться на + a, "
        "натолкну́ться на + a 2 (care for) следи́ть глаза́ми за + i"
    )
    info = apple.parse_oxford_russian(raw)
    assert info is not None
    definition = apple.AppleDefinition(lexical=info, dictionary=OXFORD_RU, raw=raw)

    assert definition.candidates() == [
        "наталкиваться на",
        "натолкнуться на",
        "следить глазами за",
    ]


def _write_fake_helper(tmp_path: Path, *, with_markup: bool = False) -> Path:
    """A stand-in for the Swift sidecar speaking the same NDJSON protocol."""
    script = tmp_path / "fake-apple-lang-helper"
    body = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys
        BANK = {BANK_RAW!r}
        MARKUP = {BANK_MARKUP!r}
        DICT = {OXFORD_RU!r}
        WITH_MARKUP = {with_markup!r}
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            rid = req.get("id", "0")
            op = req.get("op")
            term = req.get("term") or ""
            if op == "ping":
                out = {{"id": rid, "ok": True, "result": {{"pong": True, "version": "test"}}}}
            elif op in ("availability", "dictionaries"):
                out = {{"id": rid, "ok": True, "result": {{
                    "source": req.get("source", "en"), "target": req.get("target", "ru"),
                    "status": "supported",
                    "dictionaries": [{{"name": DICT, "short_name": None}}]}}}}
            elif op == "define":
                records = []
                if term.lower().startswith("bank"):
                    records.append({{"dictionary": DICT, "headword": "bank", "title": None,
                                     "anchor": None,
                                     "markup": MARKUP if WITH_MARKUP else None}})
                out = {{"id": rid, "ok": True, "result": {{"records": records, "elapsed_ms": 1.0}}}}
            elif op == "text_definition":
                text = BANK if term.lower().startswith("bank") else ""
                out = {{"id": rid, "ok": True, "result": {{"text": text, "elapsed_ms": 1.0}}}}
            elif op == "translate":
                text = req.get("text", "")
                if text.startswith("ok:"):
                    out = {{"id": rid, "ok": True, "result": {{"text": "перевод " + text[3:],
                            "source": "en", "target": "ru", "elapsed_ms": 1.0}}}}
                elif text == "crash":
                    sys.exit(3)
                else:
                    out = {{"id": rid, "ok": False, "error": {{
                        "code": "translation_not_installed", "message": "notInstalled"}}}}
            elif op == "shutdown":
                sys.stdout.write(json.dumps({{"id": rid, "ok": True, "result": {{}}}}) + "\\n")
                sys.stdout.flush()
                break
            else:
                out = {{"id": rid, "ok": False, "error": {{"code": "unknown_op", "message": op}}}}
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\\n")
            sys.stdout.flush()
        """
    )
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


@pytest.fixture
def fake_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = _write_fake_helper(tmp_path)
    monkeypatch.setenv(apple.HELPER_ENV, str(script))
    monkeypatch.delenv("TRANSLATOR_DISABLE_APPLE_ENGINES", raising=False)
    monkeypatch.setattr(apple.sys, "platform", "darwin")
    return script


def test_helper_client_defines_translates_and_reports_status(fake_helper: Path) -> None:
    async def scenario() -> None:
        helper = apple.AppleLangHelper(binary=fake_helper)
        try:
            status = await helper.status()
            assert status.translation_status == "supported"
            assert status.dictionaries == (OXFORD_RU,)
            assert not status.translation_installed

            # No markup in the records, so the client falls back to the flat
            # DCSCopyTextDefinition text and parses it itself.
            definition = await helper.define("bank")
            assert definition is not None
            assert definition.lexical.headword == "bank"
            assert definition.dictionary == OXFORD_RU
            assert await helper.define("zzz") is None

            assert await helper.translate("hello", source="en", target="ru") is None
            translated = await helper.translate("ok:hello", source="en", target="ru")
            assert translated == "перевод hello"
        finally:
            await helper.close()

    asyncio.run(scenario())


def test_helper_client_prefers_structured_records_when_markup_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With markup present the client parses it and never asks for the flat text."""
    script = _write_fake_helper(tmp_path, with_markup=True)
    monkeypatch.setattr(apple.sys, "platform", "darwin")

    async def scenario() -> apple.AppleDefinition | None:
        helper = apple.AppleLangHelper(binary=script)
        try:
            return await helper.define("bank")
        finally:
            await helper.close()

    definition = asyncio.run(scenario())

    assert definition is not None
    assert definition.raw.startswith("<?xml")  # the markup, not the flat text
    lexical = definition.lexical
    assert lexical.headword == "bank"
    assert (lexical.ipa_uk, lexical.ipa_us) == ("baŋk", "bæŋk")
    assert [entry.pos for entry in lexical.entries] == ["noun"]
    sense = lexical.entries[0].senses[0]
    assert (sense.index, sense.label, sense.translation) == (1, "of river", "бе́рег")
    assert [(pair.en, pair.ru) for pair in sense.examples] == [
        ("bank of fog", "полоса́ тума́на")
    ]
    assert definition.candidates() == ["берег"]


def test_helper_client_survives_process_crash(fake_helper: Path) -> None:
    async def scenario() -> None:
        helper = apple.AppleLangHelper(binary=fake_helper)
        try:
            with pytest.raises(apple.AppleHelperError):
                await helper.translate("crash", source="en", target="ru")
            # A fresh process is spawned for the next request.
            assert await helper.translate("ok:again", source="en", target="ru") == (
                "перевод again"
            )
        finally:
            await helper.close()

    asyncio.run(scenario())


def _write_big_reply_helper(tmp_path: Path, payload_bytes: int) -> Path:
    """A helper whose `define` reply is one very long NDJSON line."""
    script = tmp_path / "big-apple-lang-helper"
    body = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys
        BIG = "x" * {payload_bytes}
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            rid = req.get("id", "0")
            if req.get("op") == "define":
                out = {{"id": rid, "ok": True, "result": {{"records": [
                    {{"dictionary": "d", "headword": "x", "title": None,
                      "anchor": None, "markup": BIG}}]}}}}
            else:
                out = {{"id": rid, "ok": True, "result": {{"pong": True}}}}
            sys.stdout.write(json.dumps(out) + "\\n")
            sys.stdout.flush()
        """
    )
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_helper_client_reads_entries_larger_than_the_default_stream_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """asyncio streams default to 64 KB; Oxford's `set` article is ~106 KB.

    Before the limit was raised, readline() raised mid-read, the reader task
    died and every later request on that process returned nothing.
    """
    monkeypatch.setattr(apple.sys, "platform", "darwin")
    script = _write_big_reply_helper(tmp_path, 300_000)
    seen: list[int] = []

    class _FakeDcs:
        @staticmethod
        def records_from_json(payload: object) -> list[dict[str, object]]:
            assert isinstance(payload, list)
            records: list[dict[str, object]] = []
            for item in cast(list[object], payload):
                assert isinstance(item, dict)
                records.append(cast(dict[str, object], item))
            return records

        @staticmethod
        def lexical_from_records(
            records: list[dict[str, object]], *, query: str
        ) -> LexicalInfo:
            del query
            markup = records[0]["markup"]
            assert isinstance(markup, str)
            seen.append(len(markup))
            return LexicalInfo(headword="x")

    def _import_module(name: str) -> object:
        assert name.endswith("apple_dcs")
        return _FakeDcs

    monkeypatch.setattr(apple.importlib, "import_module", _import_module)

    async def scenario() -> None:
        helper = apple.AppleLangHelper(binary=script)
        try:
            definition = await helper.define("set", timeout=10.0)
            assert definition is not None
            # The process survives: a second request still answers.
            second = await helper.define("set", timeout=10.0)
            assert second is not None
        finally:
            await helper.close()

    asyncio.run(scenario())

    assert seen == [300_000, 300_000]
    assert apple.STREAM_LIMIT_BYTES > 64 * 1024


def test_lookup_runs_define_and_translate_together(fake_helper: Path) -> None:
    async def scenario() -> apple.AppleLookup:
        try:
            return await apple.lookup(
                text="ok:bank", lookup_text="bank", source_lang="en", target_lang="ru"
            )
        finally:
            await apple.close_helper()

    result = asyncio.run(scenario())

    assert result.machine_translation == "перевод bank"
    assert result.definition is not None
    assert result.definition.candidates()[0] == "берег"
    assert apple.is_available()


def test_is_available_requires_darwin_and_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(apple.HELPER_ENV, raising=False)
    monkeypatch.setattr(apple.sys, "platform", "linux")
    assert not apple.is_available()
    monkeypatch.setattr(apple.sys, "platform", "darwin")
    monkeypatch.setenv(apple.HELPER_ENV, str(Path(os.devnull) / "missing"))
    assert not apple.is_available()


def test_merge_apple_lookup_extends_translation_examples_and_lexical() -> None:
    from translate_logic.application.pipeline.translate import merge_apple_lookup

    info = apple.parse_oxford_russian(BANK_RAW)
    assert info is not None
    definition = apple.AppleDefinition(lexical=info, dictionary=OXFORD_RU, raw=BANK_RAW)
    lookup = apple.AppleLookup(definition=definition, machine_translation="банк")
    base = TranslationResult(
        translation_ru=FieldValue.present("банк; берег"),
        definitions_en=("A financial institution.",),
        examples=(Example("The bank is closed today."),),
    )

    merged = merge_apple_lookup(base, lookup, query="bank", target_lang="ru")

    assert merged.translation_ru.text.startswith("банк; берег; банка; занос")
    assert merged.definitions_en == base.definitions_en
    assert merged.lexical is info
    assert Example("The bank is closed today.") in merged.examples

    empty = TranslationResult.empty()
    recovered = merge_apple_lookup(empty, lookup, query="bank", target_lang="ru")
    assert (
        recovered.translation_ru.text
        == "берег; банка; занос; сугроб; насыпь; кренить; накренить; образовывать заносы"
    )

    phrasal = merge_apple_lookup(
        base,
        apple.AppleLookup(definition=definition, machine_translation=None),
        query="look up",
        target_lang="ru",
    )
    assert phrasal.lexical is None
    assert phrasal.translation_ru == base.translation_ru


def _entry(pos: str, translation: str) -> LexicalEntry:
    return LexicalEntry(
        pos=pos, senses=(LexicalSense(index=1, label="", translation=translation),)
    )


def test_focus_on_query_drops_foreign_phrasal_blocks() -> None:
    """`went` resolves to the whole `go` article, phrasal verbs included."""
    info = LexicalInfo(
        headword="went",
        ipa_uk="ɡɛt",
        entries=(
            _entry("noun", "движение"),
            _entry("intransitive verb", "ходить"),
            _entry("go about · intransitive verb", "приниматься"),
            _entry("go back · intransitive verb", "возвращаться"),
            _entry("go up · intransitive verb", "подниматься"),
        ),
    )

    focused = apple.focus_on_query(info, query="went")

    assert [entry.pos for entry in focused.entries] == ["noun", "intransitive verb"]
    # Everything else about the card survives.
    assert focused.headword == "went"
    assert focused.ipa_uk == "ɡɛt"


def test_focus_on_query_keeps_the_block_that_matches_the_query() -> None:
    info = LexicalInfo(
        headword="go",
        entries=(
            _entry("intransitive verb", "ходить"),
            _entry("go back · intransitive verb", "возвращаться"),
            _entry("go up · intransitive verb", "подниматься"),
        ),
    )

    focused = apple.focus_on_query(info, query="go back")

    assert [entry.pos for entry in focused.entries] == [
        "intransitive verb",
        "go back · intransitive verb",
    ]


def test_focus_on_query_leaves_plain_and_phrasal_records_untouched() -> None:
    # `look up` arrives as its own record, so nothing is labelled with a phrase.
    phrasal = LexicalInfo(
        headword="look up",
        entries=(
            _entry("transitive verb", "навещать"),
            _entry("intransitive verb", "искать"),
        ),
    )
    assert apple.focus_on_query(phrasal, query="look up") is phrasal

    # Homograph markers are not phrase labels.
    homographs = LexicalInfo(
        headword="bank",
        entries=(_entry("noun¹", "берег"), _entry("noun³", "банк")),
    )
    assert apple.focus_on_query(homographs, query="bank") is homographs

    assert apple.focus_on_query(LexicalInfo(headword="x"), query="x").entries == ()


def test_focus_on_query_keeps_everything_when_nothing_would_remain() -> None:
    # A card with only foreign phrasal blocks is still better than an empty one.
    info = LexicalInfo(
        headword="go",
        entries=(_entry("go back · intransitive verb", "возвращаться"),),
    )

    assert apple.focus_on_query(info, query="went") is info
