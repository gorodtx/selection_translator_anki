"""Apple on-device engines (Dictionary Services + Translation.framework).

The heavy lifting happens in the Swift sidecar ``apple-lang-helper`` (see
``macos/AppleLangHelper``); this module owns the long-lived subprocess, the
NDJSON request/response plumbing and the parser that turns the flat
``DCSCopyTextDefinition`` text of the Oxford Russian Dictionary into
structured senses, IPA and EN→RU example pairs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import importlib
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Final, cast

from translate_logic.domain.models import (
    ExamplePair,
    LexicalEntry,
    LexicalInfo,
    LexicalSense,
)
from translate_logic.shared.text import count_words, normalize_whitespace

HELPER_ENV: Final[str] = "TRANSLATOR_APPLE_HELPER"
HELPER_BINARY_NAME: Final[str] = "apple-lang-helper"
DEFAULT_DEFINE_TIMEOUT_S: Final[float] = 0.6
DEFAULT_TRANSLATE_TIMEOUT_S: Final[float] = 1.5
DEFAULT_STATUS_TIMEOUT_S: Final[float] = 3.0
_SPAWN_FAILURE_LIMIT: Final[int] = 3
_MAX_RECORDS: Final[int] = 8
# `apple_dcs` labels a phrasal sub-entry as "<phrase> · <part of speech>".
_PHRASAL_POS_SEPARATOR: Final[str] = " · "
# Dictionary entry markup is large: the Oxford article for `set` is ~106 KB and
# arrives as one NDJSON line. asyncio's default stream limit is 64 KB, which
# raised ValueError mid-read and silently killed the reader task.
STREAM_LIMIT_BYTES: Final[int] = 8 << 20
_TRANSLATION_UNAVAILABLE_CODES: Final[frozenset[str]] = frozenset(
    {
        "not_installed",
        "unsupported",
        "translation_not_installed",
        "translation_unsupported",
        "translation_failed",
        "unsupported_os",
    }
)
_STATUS_TTL_S: Final[float] = 300.0
_MAX_CANDIDATE_WORDS: Final[int] = 5
_COMBINING_ACUTE: Final[str] = "́"
_RU_DICTIONARY_MARKERS: Final[tuple[str, ...]] = ("Russian", "Русско", "Англо-Русский")

_LOGGER = logging.getLogger(__name__)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
type JsonObject = dict[str, JsonValue]

_POS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:(?<=\s)|^)("
    r"transitive verb|intransitive verb|reflexive verb|auxiliary verb|modal verb|"
    r"phrasal verb|predicative adjective|attributive adjective|proper noun|"
    r"plural noun|noun|verb|adjective|adverb|preposition|conjunction|pronoun|"
    r"interjection|exclamation|determiner|abbreviation|numeral|particle|prefix|suffix"
    r")(?=\s+\d{1,2}(?:\s|:)|\s*:|\s+\(|\s*▸|\s+[А-Яа-яЁё]|\s*$)"
)
_SENSE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:(?<=\s)|^)(\d{1,2})(?=\s|:)")
_CYRILLIC_RE: Final[re.Pattern[str]] = re.compile(r"[А-Яа-яЁё]")
_LEADING_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^\(([^()]*)\)\s*:?\s*")
_ASPECT_RE: Final[re.Pattern[str]] = re.compile(r"\((?:impf|pf|impf\.|pf\.)\)")
_HOMOGRAPH_RE: Final[re.Pattern[str]] = re.compile(r"\s+\d+$")
_IPA_RE: Final[re.Pattern[str]] = re.compile(r"(BrE|AmE)\s+([^,|]+)")
_TRAILING_GLOSS_RE: Final[re.Pattern[str]] = re.compile(r"\s*\([^()А-Яа-яЁё]*\)\s*$")
_LATIN_OR_OPERATOR_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z+=]")
# The case a verb governs, written as a latin letter after a plus: "наталкиваться
# на + a", "следить за + i". Same rule as apple_dcs._CASE_MARKER_RE; both cleaners
# have to agree, since the flat-text path never reaches that module.
_CASE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"\s*\+\s*[a-z]{1,2}\b\.?")


def _new_pending() -> dict[str, asyncio.Future[JsonObject]]:
    return {}


class AppleHelperError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AppleDefinition:
    lexical: LexicalInfo
    dictionary: str
    raw: str

    def matches(self, query: str) -> bool:
        return _normalize_key(self.lexical.headword) == _normalize_key(query)

    def candidates(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in self.lexical.entries:
            for sense in entry.senses:
                for candidate in _translation_candidates(sense.translation):
                    key = candidate.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    ordered.append(candidate)
        return ordered

    def example_sentences(self) -> list[str]:
        sentences: list[str] = []
        for entry in self.lexical.entries:
            for sense in entry.senses:
                for pair in sense.examples:
                    if pair.en:
                        sentences.append(pair.en)
        return sentences


@dataclass(frozen=True, slots=True)
class AppleLookup:
    definition: AppleDefinition | None
    machine_translation: str | None

    @property
    def is_empty(self) -> bool:
        return self.definition is None and not self.machine_translation


@dataclass(frozen=True, slots=True)
class AppleEngineStatus:
    dictionary_available: bool
    dictionaries: tuple[str, ...]
    translation_status: str
    checked_at: float

    @property
    def translation_installed(self) -> bool:
        return self.translation_status == "installed"


# --- binary discovery --------------------------------------------------------------


def helper_binary_path() -> Path | None:
    override = os.environ.get(HELPER_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.exists() else None
    for candidate in _helper_candidates():
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _helper_candidates() -> list[Path]:
    candidates: list[Path] = []
    executable = Path(sys.executable).resolve()
    for parent in list(executable.parents)[:4]:
        candidates.append(parent / "bin" / HELPER_BINARY_NAME)
        candidates.append(parent / "Resources" / "bin" / HELPER_BINARY_NAME)
    repo_root = Path(__file__).resolve().parents[3]
    build_dir = repo_root / "macos" / "AppleLangHelper" / ".build"
    candidates.append(build_dir / "release" / HELPER_BINARY_NAME)
    candidates.append(build_dir / "debug" / HELPER_BINARY_NAME)
    return candidates


def is_available() -> bool:
    if sys.platform != "darwin":
        return False
    if os.environ.get("TRANSLATOR_DISABLE_APPLE_ENGINES", "").strip() == "1":
        return False
    return helper_binary_path() is not None


# --- subprocess client -------------------------------------------------------------------


@dataclass(slots=True)
class AppleLangHelper:
    """Client for the ``apple-lang-helper`` sidecar (NDJSON over stdio).

    Protocol (see ``macos/AppleLangHelper``): requests carry a string ``id``
    and an ``op`` (``ping``/``availability``/``dictionaries``/``define``/
    ``text_definition``/``translate``/``shutdown``); responses echo the id
    with ``ok`` plus ``result`` or ``error{code,message}``.
    """

    binary: Path
    _process: asyncio.subprocess.Process | None = None
    _reader: asyncio.Task[None] | None = None
    _pending: dict[str, asyncio.Future[JsonObject]] = field(
        default_factory=_new_pending
    )
    _next_id: int = 1
    _spawn_failures: int = 0
    _lock: asyncio.Lock | None = None

    async def define(
        self, text: str, *, timeout: float = DEFAULT_DEFINE_TIMEOUT_S
    ) -> AppleDefinition | None:
        result = await self.request(
            "define",
            timeout=timeout,
            term=text,
            max_records=_MAX_RECORDS,
            include_markup=True,
        )
        definition = _definition_from_records(result, query=text)
        if definition is not None:
            return definition
        dictionary = _first_record_dictionary(result)
        flat = await self.request("text_definition", timeout=timeout, term=text)
        raw = flat.get("text")
        if not isinstance(raw, str) or not raw.strip():
            return None
        return _definition_from_flat_text(raw, dictionary=dictionary, query=text)

    async def translate(
        self,
        text: str,
        *,
        source: str,
        target: str,
        timeout: float = DEFAULT_TRANSLATE_TIMEOUT_S,
    ) -> str | None:
        try:
            result = await self.request(
                "translate", timeout=timeout, text=text, source=source, target=target
            )
        except AppleHelperError as exc:
            if exc.code in _TRANSLATION_UNAVAILABLE_CODES:
                return None
            raise
        translated = result.get("text")
        if not isinstance(translated, str):
            return None
        normalized = normalize_whitespace(translated)
        return normalized or None

    async def status(
        self,
        *,
        source: str = "en",
        target: str = "ru",
        timeout: float = DEFAULT_STATUS_TIMEOUT_S,
    ) -> AppleEngineStatus:
        result = await self.request(
            "availability", timeout=timeout, source=source, target=target
        )
        dictionaries = _dictionary_names(result.get("dictionaries"))
        raw_status = result.get("status")
        status = raw_status if isinstance(raw_status, str) else "unknown"
        return AppleEngineStatus(
            dictionary_available=bool(dictionaries),
            dictionaries=dictionaries,
            translation_status=status,
            checked_at=time.monotonic(),
        )

    async def request(
        self, op: str, *, timeout: float, **fields: JsonValue
    ) -> JsonObject:
        process = await self._ensure_process()
        if process.stdin is None:
            raise AppleHelperError("spawn_failed", "helper stdin unavailable")
        loop = asyncio.get_running_loop()
        request_id = str(self._next_id)
        self._next_id += 1
        payload: JsonObject = {"id": request_id, "op": op}
        for key, value in fields.items():
            if value is not None:
                payload[key] = value
        future: asyncio.Future[JsonObject] = loop.create_future()
        self._pending[request_id] = future
        try:
            process.stdin.write(
                json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
            )
            await process.stdin.drain()
            message = await asyncio.wait_for(future, timeout)
        except TimeoutError as exc:
            raise AppleHelperError(
                "timeout", f"{op} timed out after {timeout}s"
            ) from exc
        finally:
            self._pending.pop(request_id, None)
        if message.get("ok") is True or (
            "ok" not in message and message.get("error") is None
        ):
            result = message.get("result")
            return result if isinstance(result, dict) else {}
        error = message.get("error")
        code = "helper_error"
        detail = "helper request failed"
        if isinstance(error, dict):
            raw_code = error.get("code")
            raw_message = error.get("message")
            if isinstance(raw_code, str):
                code = raw_code
            if isinstance(raw_message, str):
                detail = raw_message
        raise AppleHelperError(code, detail)

    async def close(self) -> None:
        process = self._process
        self._process = None
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 1.0)
        except (TimeoutError, ProcessLookupError):
            process.kill()

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            process = self._process
            if process is not None and process.returncode is None:
                return process
            if self._spawn_failures >= _SPAWN_FAILURE_LIMIT:
                raise AppleHelperError("unavailable", "helper keeps exiting; giving up")
            try:
                process = await asyncio.create_subprocess_exec(
                    str(self.binary),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=STREAM_LIMIT_BYTES,
                )
            except OSError as exc:
                self._spawn_failures += 1
                raise AppleHelperError("spawn_failed", str(exc)) from exc
            self._process = process
            self._reader = asyncio.create_task(self._read_loop(process))
            return process

    async def _read_loop(self, process: asyncio.subprocess.Process) -> None:
        stdout = process.stdout
        assert stdout is not None
        try:
            while True:
                try:
                    line = await stdout.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    # One oversized entry must not take the sidecar down with it.
                    _LOGGER.warning("apple helper sent an oversized line; dropping it")
                    continue
                if not line:
                    break
                try:
                    decoded: object = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                message = _as_object(decoded)
                if message is None:
                    continue
                raw_id = message.get("id")
                if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
                    continue
                future = self._pending.get(str(raw_id))
                if future is not None and not future.done():
                    future.set_result(message)
                    self._spawn_failures = 0
        finally:
            if self._process is process:
                self._process = None
                self._spawn_failures += 1
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(
                        AppleHelperError("helper_exited", "helper exited")
                    )
            self._pending.clear()


@dataclass(slots=True)
class _StatusCache:
    value: AppleEngineStatus | None = None


_HELPERS: dict[int, AppleLangHelper] = {}
_status_cache = _StatusCache()


def get_helper() -> AppleLangHelper | None:
    if not is_available():
        return None
    binary = helper_binary_path()
    if binary is None:
        return None
    loop = asyncio.get_running_loop()
    key = id(loop)
    helper = _HELPERS.get(key)
    if helper is None or helper.binary != binary:
        helper = AppleLangHelper(binary=binary)
        _HELPERS[key] = helper
    return helper


async def close_helper() -> None:
    """Terminate the sidecar bound to the running loop (tests, shutdown)."""
    helper = _HELPERS.pop(id(asyncio.get_running_loop()), None)
    if helper is not None:
        await helper.close()


async def lookup(
    *,
    text: str,
    lookup_text: str,
    source_lang: str,
    target_lang: str,
    define_timeout: float = DEFAULT_DEFINE_TIMEOUT_S,
    translate_timeout: float = DEFAULT_TRANSLATE_TIMEOUT_S,
) -> AppleLookup:
    helper = get_helper()
    if helper is None:
        return AppleLookup(definition=None, machine_translation=None)
    define_task = asyncio.create_task(
        _safe_define(helper, lookup_text, timeout=define_timeout)
    )
    translate_task = asyncio.create_task(
        _safe_translate(
            helper,
            text,
            source=source_lang,
            target=target_lang,
            timeout=translate_timeout,
        )
    )
    definition, translation = await asyncio.gather(define_task, translate_task)
    return AppleLookup(definition=definition, machine_translation=translation)


async def refresh_status(
    *, source: str = "en", target: str = "ru"
) -> AppleEngineStatus | None:
    helper = get_helper()
    if helper is None:
        return None
    try:
        status = await helper.status(source=source, target=target)
    except AppleHelperError as exc:
        _LOGGER.warning("apple helper status failed: %s", exc.message)
        return None
    _status_cache.value = status
    return status


def last_status() -> AppleEngineStatus | None:
    return _status_cache.value


def engine_status() -> dict[str, JsonValue]:
    status = _status_cache.value
    available = is_available()
    stale = status is None or (time.monotonic() - status.checked_at) > _STATUS_TTL_S
    return {
        "apple_dictionary": available
        and status is not None
        and status.dictionary_available,
        "apple_translation": available
        and status is not None
        and status.translation_installed,
        "translation_status": status.translation_status
        if status is not None
        else "unknown",
        "dictionaries": list(status.dictionaries) if status is not None else [],
        "helper": str(helper_binary_path()) if available else None,
        "stale": stale,
    }


async def _safe_define(
    helper: AppleLangHelper, text: str, *, timeout: float
) -> AppleDefinition | None:
    try:
        return await helper.define(text, timeout=timeout)
    except AppleHelperError as exc:
        _LOGGER.debug("apple define failed: %s", exc.message)
        return None


async def _safe_translate(
    helper: AppleLangHelper, text: str, *, source: str, target: str, timeout: float
) -> str | None:
    try:
        return await helper.translate(
            text, source=source, target=target, timeout=timeout
        )
    except AppleHelperError as exc:
        _LOGGER.debug("apple translate failed: %s", exc.message)
        return None


# --- parsing -------------------------------------------------------------------------------


def _dictionary_names(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
            continue
        entry = _as_object(item)
        if entry is None:
            continue
        name = entry.get("name")
        if isinstance(name, str):
            names.append(name)
    return tuple(names)


def _first_record_dictionary(result: JsonObject) -> str:
    records = result.get("records")
    if isinstance(records, list):
        for item in records:
            record = _as_object(item)
            if record is None:
                continue
            dictionary = record.get("dictionary")
            if isinstance(dictionary, str) and dictionary:
                return dictionary
    return ""


def _definition_from_records(
    result: JsonObject, *, query: str
) -> AppleDefinition | None:
    """Structured path: XHTML records parsed by ``apple_dcs`` when present."""
    records_raw = result.get("records")
    if not isinstance(records_raw, list) or not records_raw:
        return None
    if not any(
        isinstance(record := _as_object(item), dict)
        and isinstance(record.get("markup"), str)
        for item in records_raw
    ):
        return None
    try:
        module = importlib.import_module(
            "translate_logic.infrastructure.providers.apple_dcs"
        )
    except ImportError:
        return None
    records_from_json = cast(
        Callable[[object], Sequence[object]], getattr(module, "records_from_json")
    )
    lexical_from_records = cast(
        Callable[..., LexicalInfo | None], getattr(module, "lexical_from_records")
    )
    records = records_from_json(records_raw)
    lexical = lexical_from_records(records, query=query)
    if lexical is None:
        return None
    lexical = focus_on_query(lexical, query=query)
    dictionary = _first_record_dictionary(result)
    first_markup = ""
    first = _as_object(records_raw[0])
    if first is not None:
        markup = first.get("markup")
        if isinstance(markup, str):
            first_markup = markup
    return AppleDefinition(lexical=lexical, dictionary=dictionary, raw=first_markup)


def focus_on_query(info: LexicalInfo, *, query: str) -> LexicalInfo:
    """Drop phrasal sub-entries that belong to a different phrase.

    An inflected form resolves to the base article: `went` returns all of `go`,
    whose 26 blocks include 22 phrasal verbs (`go about`, `go back`, ...). None
    of them translate the query, and they crowd both the card and the candidate
    list. A block is kept when its part of speech names no phrase, or names the
    query itself, so `look up` (already a phrasal record) survives untouched.
    """
    if not info.entries:
        return info
    normalized_query = _normalize_key(query)
    kept = tuple(
        entry
        for entry in info.entries
        if _entry_phrase(entry.pos) in {"", normalized_query}
    )
    if len(kept) == len(info.entries):
        return info
    if not kept:
        return info
    return LexicalInfo(
        headword=info.headword,
        ipa_uk=info.ipa_uk,
        ipa_us=info.ipa_us,
        entries=kept,
        source=info.source,
    )


def _entry_phrase(pos: str) -> str:
    """The phrase a phrasal sub-entry belongs to, or "" for a plain block."""
    head, separator, _ = pos.partition(_PHRASAL_POS_SEPARATOR)
    if not separator:
        return ""
    return _normalize_key(head)


def _definition_from_flat_text(
    raw: str, *, dictionary: str, query: str
) -> AppleDefinition | None:
    """Fallback path: the flat ``DCSCopyTextDefinition`` string."""
    if dictionary and not any(
        marker in dictionary for marker in _RU_DICTIONARY_MARKERS
    ):
        return None
    lexical = parse_oxford_russian(raw)
    if lexical is None:
        return None
    definition = AppleDefinition(
        lexical=lexical, dictionary=dictionary or "default", raw=raw
    )
    del query
    return definition


def parse_oxford_russian(raw: str) -> LexicalInfo | None:
    text = normalize_whitespace(raw)
    if not text:
        return None
    head, separator, rest = text.partition(" | ")
    if not separator:
        return None
    headword = _HOMOGRAPH_RE.sub("", head).strip()
    ipa_uk = ""
    ipa_us = ""
    pronunciation, separator, body = rest.partition(" | ")
    if separator and ("BrE" in pronunciation or "AmE" in pronunciation):
        for variant, value in _IPA_RE.findall(pronunciation):
            if variant == "BrE":
                ipa_uk = value.strip()
            else:
                ipa_us = value.strip()
    else:
        body = rest
    entries = tuple(_parse_entries(body))
    if not headword or (not entries and not ipa_uk and not ipa_us):
        return None
    return LexicalInfo(headword=headword, ipa_uk=ipa_uk, ipa_us=ipa_us, entries=entries)


def _parse_entries(body: str) -> list[LexicalEntry]:
    matches = list(_POS_PATTERN.finditer(body))
    entries: list[LexicalEntry] = []
    if not matches:
        senses = _parse_senses(body)
        return [LexicalEntry(pos="", senses=tuple(senses))] if senses else []
    if matches[0].start() > 0:
        leading = body[: matches[0].start()].strip()
        leading_senses = _parse_senses(leading)
        if leading_senses:
            entries.append(LexicalEntry(pos="", senses=tuple(leading_senses)))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[match.end() : end].strip()
        senses = _parse_senses(chunk)
        if senses:
            entries.append(LexicalEntry(pos=match.group(1), senses=tuple(senses)))
    return entries


def _parse_senses(chunk: str) -> list[LexicalSense]:
    chunk = chunk.strip().lstrip(":").strip()
    if not chunk:
        return []
    markers = list(_SENSE_PATTERN.finditer(chunk))
    if not markers:
        sense = _parse_sense(1, chunk)
        return [sense] if sense is not None else []
    senses: list[LexicalSense] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(chunk)
        text = chunk[marker.end() : end].strip().lstrip(":").strip()
        sense = _parse_sense(int(marker.group(1)), text)
        if sense is not None:
            senses.append(sense)
    return senses


def _parse_sense(index: int, text: str) -> LexicalSense | None:
    if not text:
        return None
    translation_part, _, examples_part = text.partition("▸")
    labels: list[str] = []
    remaining = translation_part.strip()
    while True:
        match = _LEADING_LABEL_RE.match(remaining)
        if match is None or _CYRILLIC_RE.search(match.group(1)):
            break
        labels.append(match.group(1).strip())
        remaining = remaining[match.end() :].strip()
    translation = normalize_whitespace(remaining.strip(" :"))
    examples = tuple(_parse_examples(examples_part))
    if not translation and not examples:
        return None
    return LexicalSense(
        index=index,
        label="; ".join(labels),
        translation=translation,
        examples=examples,
    )


def _parse_examples(part: str) -> list[ExamplePair]:
    pairs: list[ExamplePair] = []
    for fragment in part.split("▸"):
        fragment = fragment.strip()
        if not fragment:
            continue
        fragment = _LEADING_LABEL_RE.sub("", fragment).strip()
        match = _CYRILLIC_RE.search(fragment)
        if match is None:
            continue
        en = normalize_whitespace(fragment[: match.start()].strip(" :,;(")).strip()
        en = _TRAILING_GLOSS_RE.sub("", en).strip()
        ru = normalize_whitespace(fragment[match.start() :]).strip()
        if not en or not ru:
            continue
        pairs.append(ExamplePair(en=en, ru=ru))
    return pairs


def _unwrap(fragment: str) -> str:
    """Drop brackets that wrap a whole fragment, keeping an ordinary qualifier intact.

    ``strip("()")`` would also eat the closing bracket of "настоя́щее (вре́мя)".
    """
    if fragment.startswith("(") and fragment.endswith(")"):
        return fragment[1:-1].strip()
    return fragment


def _translation_candidates(translation: str) -> list[str]:
    if not translation:
        return []
    cleaned = translation.replace(_COMBINING_ACUTE, "")
    cleaned = _ASPECT_RE.sub("", cleaned)
    cleaned = cleaned.replace("|", "")
    cleaned = re.sub(r"\((?:[^()]*[A-Za-z][^()]*)\)", "", cleaned)
    cleaned = _CASE_MARKER_RE.sub("", cleaned)
    candidates: list[str] = []
    for piece in re.split(r"[/,;]", cleaned):
        piece = _unwrap(piece.strip())
        if piece.count("(") != piece.count(")"):
            # A qualifier the split cut in half; the halves are not translations.
            continue
        tokens = piece.split()
        # Dangling prefixes/endings ("по-", "-ать") mark inflection notes, not
        # standalone translations; drop the whole fragment.
        if any(token.startswith("-") or token.endswith("-") for token in tokens):
            continue
        piece = normalize_whitespace(" ".join(tokens))
        if not piece or not _CYRILLIC_RE.search(piece):
            continue
        if _LATIN_OR_OPERATOR_RE.search(piece):
            continue
        if count_words(piece) > _MAX_CANDIDATE_WORDS:
            continue
        candidates.append(piece)
    return candidates


def _as_object(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    items = cast(dict[object, object], value)
    return {str(key): cast(JsonValue, item) for key, item in items.items()}


def _normalize_key(value: str) -> str:
    return normalize_whitespace(value.replace(_COMBINING_ACUTE, "")).casefold()
