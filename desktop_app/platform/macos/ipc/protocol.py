"""Wire protocol between the native macOS shell and the Python backend.

Transport: Unix domain socket, newline-delimited JSON (UTF-8), one object per
line. Requests carry ``id``/``method``/``params``; responses echo ``id`` with
``ok`` + ``result`` or ``error``; server-initiated events carry ``event`` +
``payload`` and no ``id``. This module is the single source of truth for the
message shapes; the SwiftUI client mirrors it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Final, cast

from desktop_app.application.anki_status import AnkiActionResult, AnkiStatus
from desktop_app.application.history import HistoryItem
from desktop_app.application.use_cases.anki_upsert import (
    AnkiFieldAction,
    AnkiImageAction,
    AnkiUpsertDecision,
    AnkiUpsertPreview,
)
from desktop_app.application.view_state import TranslationViewState
from desktop_app.config import AppConfig, JsonValue, config_from_dict, config_to_dict
from desktop_app.infrastructure.anki import AnkiListResult
from desktop_app.infrastructure.notifications.models import Notification
from translate_logic.models import LexicalInfo

PROTOCOL_VERSION: Final[int] = 1
MAX_LINE_BYTES: Final[int] = 1 << 20

type JsonObject = dict[str, JsonValue]
type RequestId = str | int


class Method(StrEnum):
    PING = "ping"
    TRANSLATE = "translate"
    CANCEL = "cancel"
    CLOSE = "close"
    HISTORY_LIST = "history.list"
    HISTORY_SELECT = "history.select"
    EXAMPLES_REFRESH = "examples.refresh"
    COPY_ALL = "copy_all"
    ANKI_STATUS = "anki.status"
    ANKI_DECKS = "anki.decks"
    ANKI_MODEL_FIELDS = "anki.model_fields"
    ANKI_SELECT_DECK = "anki.select_deck"
    ANKI_CREATE_MODEL = "anki.create_model"
    ANKI_PREPARE_UPSERT = "anki.prepare_upsert"
    ANKI_APPLY_UPSERT = "anki.apply_upsert"
    ENGINES_REFRESH = "engines.refresh"
    DB_DOWNLOAD = "db.download"
    DB_CANCEL = "db.cancel"
    SETTINGS_GET = "settings.get"
    SETTINGS_SAVE = "settings.save"
    SHUTDOWN = "shutdown"


class Event(StrEnum):
    TRANSLATION_STATE = "translation.state"
    NOTIFICATION = "notification"
    ANKI_AVAILABILITY = "anki.availability"
    DB_PROGRESS = "db.progress"


class Phase(StrEnum):
    BEGIN = "begin"
    PARTIAL = "partial"
    FINAL = "final"
    ERROR = "error"
    EXAMPLES = "examples"


class ErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    UNKNOWN_METHOD = "unknown_method"
    INVALID_PARAMS = "invalid_params"
    NOT_READY = "not_ready"
    NO_ACTIVE_ENTRY = "no_active_entry"
    ANKI = "anki_error"
    INTERNAL = "internal"


class ProtocolDecodeError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Request:
    id: RequestId
    method: str
    params: JsonObject


@dataclass(frozen=True, slots=True)
class ProtocolError:
    code: ErrorCode
    message: str


def encode_line(payload: JsonObject) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def encode_response(request_id: RequestId, result: JsonObject) -> bytes:
    return encode_line({"id": request_id, "ok": True, "result": result})


def encode_error(request_id: RequestId | None, error: ProtocolError) -> bytes:
    return encode_line(
        {
            "id": request_id,
            "ok": False,
            "error": {"code": str(error.code), "message": error.message},
        }
    )


def encode_event(event: Event, payload: JsonObject) -> bytes:
    return encode_line({"event": str(event), "payload": payload})


def decode_request(line: bytes | str) -> Request:
    raw = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
    raw = raw.strip()
    if not raw:
        raise ProtocolDecodeError(ErrorCode.BAD_REQUEST, "Empty request line.")
    try:
        payload: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolDecodeError(
            ErrorCode.BAD_REQUEST, f"Malformed JSON: {exc.msg}."
        ) from exc
    payload_dict = as_json_object(payload)
    if payload_dict is None:
        raise ProtocolDecodeError(ErrorCode.BAD_REQUEST, "Request must be an object.")
    request_id = payload_dict.get("id")
    if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
        raise ProtocolDecodeError(ErrorCode.BAD_REQUEST, "Request id must be str|int.")
    method = payload_dict.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolDecodeError(ErrorCode.BAD_REQUEST, "Request method is required.")
    params = payload_dict.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolDecodeError(ErrorCode.INVALID_PARAMS, "params must be an object.")
    return Request(id=request_id, method=method, params=params)


def as_json_object(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    items = cast(dict[object, object], value)
    result: JsonObject = {}
    for key, item in items.items():
        result[str(key)] = cast(JsonValue, item)
    return result


def get_str(params: JsonObject, key: str, *, required: bool = True) -> str:
    value = params.get(key)
    if isinstance(value, str):
        return value
    if value is None and not required:
        return ""
    raise ProtocolDecodeError(ErrorCode.INVALID_PARAMS, f"'{key}' must be a string.")


def get_int(params: JsonObject, key: str) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolDecodeError(
            ErrorCode.INVALID_PARAMS, f"'{key}' must be an integer."
        )
    return value


def get_object(params: JsonObject, key: str) -> JsonObject:
    value = params.get(key)
    if not isinstance(value, dict):
        raise ProtocolDecodeError(
            ErrorCode.INVALID_PARAMS, f"'{key}' must be an object."
        )
    return value


# --- domain → JSON -----------------------------------------------------------


def lexical_to_json(info: LexicalInfo | None) -> JsonObject | None:
    if info is None:
        return None
    entries: list[JsonValue] = []
    for entry in info.entries:
        senses: list[JsonValue] = []
        for sense in entry.senses:
            senses.append(
                {
                    "index": sense.index,
                    "label": sense.label,
                    "translation": sense.translation,
                    "examples": [
                        {"en": pair.en, "ru": pair.ru} for pair in sense.examples
                    ],
                }
            )
        entries.append({"pos": entry.pos, "senses": senses})
    return {
        "headword": info.headword,
        "ipa_uk": info.ipa_uk,
        "ipa_us": info.ipa_us,
        "entries": entries,
        "source": info.source,
    }


def view_state_to_json(
    state: TranslationViewState,
    *,
    entry_id: int | None,
    lexical: LexicalInfo | None = None,
    translation_raw: str | None = None,
) -> JsonObject:
    return {
        "original": state.original,
        "original_raw": state.original_raw,
        "translation": state.translation,
        # ``translation`` is hard-wrapped for the GTK label; native clients
        # should lay out the unwrapped text themselves.
        "translation_raw": (
            translation_raw
            if translation_raw is not None
            else state.translation.replace("\n", " ")
        ),
        "definitions_items": list(state.definitions_items),
        "examples": [{"en": item.en} for item in state.examples],
        "can_refresh_examples": state.can_refresh_examples,
        "refreshing_examples": state.refreshing_examples,
        "loading": state.loading,
        "can_add_anki": state.can_add_anki,
        "entry_id": entry_id,
        "apple": lexical_to_json(lexical),
    }


def translation_state_event(
    *,
    request_id: int,
    phase: Phase,
    state: TranslationViewState,
    entry_id: int | None,
    lexical: LexicalInfo | None = None,
    translation_raw: str | None = None,
) -> JsonObject:
    return {
        "request_id": request_id,
        "phase": str(phase),
        "state": view_state_to_json(
            state,
            entry_id=entry_id,
            lexical=lexical,
            translation_raw=translation_raw,
        ),
    }


def history_item_to_json(item: HistoryItem) -> JsonObject:
    return {
        "entry_id": item.entry_id,
        "text": item.text,
        "lookup_text": item.lookup_text,
        "translation": item.result.translation_ru.text,
        "definitions_en": list(item.result.definitions_en),
        "examples": [example.en for example in item.examples_state.visible_examples],
    }


def notification_to_json(notification: Notification) -> JsonObject:
    return {"message": notification.message, "level": notification.level.value}


def anki_status_to_json(status: AnkiStatus, *, available: bool) -> JsonObject:
    return {
        "model_status": status.model_status,
        "deck_status": status.deck_status,
        "deck_name": status.deck_name,
        "available": available,
    }


def action_result_to_json(result: AnkiActionResult) -> JsonObject:
    return {
        "message": result.message,
        "model_status": result.status.model_status,
        "deck_status": result.status.deck_status,
        "deck_name": result.status.deck_name,
    }


def deck_list_to_json(result: AnkiListResult) -> JsonObject:
    return {"decks": list(result.items), "error": result.error}


def field_list_to_json(result: AnkiListResult) -> JsonObject:
    """An empty list is "nothing to compare against", never "all names wrong".

    `error` says nobody could be asked — Anki closed, no note type configured —
    and a client that ignores it will report a mismatch when Anki is merely not
    running. But an empty list without an error is not proof of a fieldless
    note type either: against the fake, a note type that does not exist answers
    exactly like one with no fields. So the rule for the client is the same in
    both cases: with no names in hand, mark nothing as missing.
    """
    return {"fields": list(result.items), "error": result.error}


def anki_preview_to_json(preview: AnkiUpsertPreview) -> JsonObject:
    values = preview.values
    return {
        "values": {
            "translations": list(values.translations),
            "definitions_en": list(values.definitions_en),
            "examples_en": list(values.examples_en),
            "image_path": values.image_path,
        },
        "matches": [
            {
                "note_id": match.note_id,
                "word": match.word,
                "translation": match.translation,
                "definitions_en": match.definitions_en,
                "examples_en": match.examples_en,
                "image": match.image,
            }
            for match in preview.matches
        ],
        "available_fields": list(preview.available_fields),
    }


def db_progress_to_json(
    *, file: str, state: str, received: int, total: int, error: str | None
) -> JsonObject:
    return {
        "file": file,
        "state": state,
        "received": received,
        "total": total,
        "error": error,
    }


def config_to_json(config: AppConfig) -> JsonObject:
    return config_to_dict(config)


# --- JSON → domain -----------------------------------------------------------


def anki_decision_from_json(payload: JsonObject) -> AnkiUpsertDecision:
    def _field_action(key: str) -> AnkiFieldAction:
        raw = payload.get(key, AnkiFieldAction.KEEP_EXISTING.value)
        if not isinstance(raw, str):
            raise ProtocolDecodeError(
                ErrorCode.INVALID_PARAMS, f"'{key}' must be a string."
            )
        try:
            return AnkiFieldAction(raw)
        except ValueError as exc:
            raise ProtocolDecodeError(
                ErrorCode.INVALID_PARAMS, f"'{key}' has unknown value {raw!r}."
            ) from exc

    image_raw = payload.get("image_action", AnkiImageAction.KEEP_EXISTING.value)
    if not isinstance(image_raw, str):
        raise ProtocolDecodeError(
            ErrorCode.INVALID_PARAMS, "'image_action' must be a string."
        )
    try:
        image_action = AnkiImageAction(image_raw)
    except ValueError as exc:
        raise ProtocolDecodeError(
            ErrorCode.INVALID_PARAMS, f"'image_action' has unknown value {image_raw!r}."
        ) from exc
    create_new = payload.get("create_new", False)
    if not isinstance(create_new, bool):
        raise ProtocolDecodeError(
            ErrorCode.INVALID_PARAMS, "'create_new' must be a boolean."
        )
    image_path = payload.get("image_path")
    if image_path is not None and not isinstance(image_path, str):
        raise ProtocolDecodeError(
            ErrorCode.INVALID_PARAMS, "'image_path' must be a string."
        )
    return AnkiUpsertDecision(
        create_new=create_new,
        target_note_ids=_int_tuple(payload, "target_note_ids"),
        translation_action=_field_action("translation_action"),
        definitions_action=_field_action("definitions_action"),
        examples_action=_field_action("examples_action"),
        image_action=image_action,
        selected_translations=_str_tuple(payload, "selected_translations"),
        selected_definitions_en=_str_tuple(payload, "selected_definitions_en"),
        selected_examples_en=_str_tuple(payload, "selected_examples_en"),
        image_path=image_path or None,
    )


_SOURCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "apple_dictionary",
        "apple_translation",
        "google",
        "cambridge",
        "offline_examples",
        "definitions_pack",
    }
)


def config_from_json(payload: JsonObject) -> AppConfig:
    """Stricter than reading the config file, deliberately.

    Loading a file must be forgiving: one written before a key existed has to
    keep working, so a missing or unreadable block falls back to "everything
    on". A client saving settings is the opposite case — a malformed block
    there silently re-enabled every source the user had switched off, and
    answered "Settings saved". Refuse it instead.
    """
    if "sources" in payload:
        sources = payload["sources"]
        if not isinstance(sources, dict):
            raise ProtocolDecodeError(
                ErrorCode.INVALID_PARAMS, "'sources' must be an object"
            )
        for key, value in sources.items():
            if key not in _SOURCE_KEYS:
                raise ProtocolDecodeError(
                    ErrorCode.INVALID_PARAMS, f"unknown source {key!r}"
                )
            if not isinstance(value, bool):
                raise ProtocolDecodeError(
                    ErrorCode.INVALID_PARAMS, f"source {key!r} must be true or false"
                )
    return config_from_dict(payload)


def _str_tuple(payload: JsonObject, key: str) -> tuple[str, ...]:
    raw = payload.get(key, [])
    if not isinstance(raw, list):
        raise ProtocolDecodeError(ErrorCode.INVALID_PARAMS, f"'{key}' must be a list.")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ProtocolDecodeError(
                ErrorCode.INVALID_PARAMS, f"'{key}' must contain only strings."
            )
        values.append(item)
    return tuple(values)


def _int_tuple(payload: JsonObject, key: str) -> tuple[int, ...]:
    raw = payload.get(key, [])
    if not isinstance(raw, list):
        raise ProtocolDecodeError(ErrorCode.INVALID_PARAMS, f"'{key}' must be a list.")
    values: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ProtocolDecodeError(
                ErrorCode.INVALID_PARAMS, f"'{key}' must contain only integers."
            )
        values.append(item)
    return tuple(values)
