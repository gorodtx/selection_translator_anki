from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat
import sys
import textwrap

import pytest

from translate_logic.infrastructure.providers import apple
from translate_logic.models import Example, FieldValue, TranslationResult

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

    assert definition.candidates() == ["смотреть", "казаться"]


def _write_fake_helper(tmp_path: Path) -> Path:
    script = tmp_path / "fake-apple-lang-helper"
    body = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys
        BANK = {BANK_RAW!r}
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            rid = req.get("id", 0)
            op = req.get("op")
            if op == "status":
                out = {{"id": rid, "ok": True, "result": {{"dictionaries": ["{OXFORD_RU}"],
                        "translation": {{"status": "supported", "supportedCount": 38}}}}}}
            elif op == "define":
                hits = []
                if req.get("text", "").lower().startswith("bank"):
                    hits.append({{"dictionary": "{OXFORD_RU}", "raw": BANK}})
                out = {{"id": rid, "ok": True, "result": {{"results": hits}}}}
            elif op == "translate":
                text = req.get("text", "")
                if text.startswith("ok:"):
                    out = {{"id": rid, "ok": True, "result": {{"text": "перевод " + text[3:], "source": "en", "target": "ru"}}}}
                elif text == "crash":
                    sys.exit(3)
                else:
                    out = {{"id": rid, "ok": False, "error": {{"code": "not_installed", "message": "notInstalled"}}}}
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

            definition = await helper.define("bank")
            assert definition is not None
            assert definition.lexical.headword == "bank"
            assert await helper.define("zzz") is None

            assert await helper.translate("hello", source="en", target="ru") is None
            translated = await helper.translate("ok:hello", source="en", target="ru")
            assert translated == "перевод hello"
        finally:
            await helper.close()

    asyncio.run(scenario())


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
