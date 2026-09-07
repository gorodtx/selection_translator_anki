"""An in-process AnkiConnect stand-in.

Anki cannot be installed on a build machine, yet the add/update/merge/image flow
is the part of this project most likely to break silently: it spans field
mapping, HTML shaping, duplicate detection and media upload. This serves the
real AnkiConnect wire protocol over a local socket so the whole flow can be
driven end to end.

Only the actions the client actually calls are implemented; anything else comes
back as an error, the same way a version mismatch would.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import re
from threading import Thread
from typing import Final, cast
from http.server import BaseHTTPRequestHandler, HTTPServer

EXPECTED_VERSION: Final[int] = 6

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
type JsonObject = dict[str, JsonValue]


def _as_object(value: JsonValue | None) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return value


def _as_str(value: JsonValue | None) -> str:
    return value if isinstance(value, str) else ""


def _as_int(value: JsonValue | None) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _as_list(value: JsonValue | None) -> list[JsonValue]:
    return value if isinstance(value, list) else []


@dataclass
class Note:
    note_id: int
    model: str
    deck: str
    fields: dict[str, str]


@dataclass
class FakeAnkiState:
    decks: list[str] = field(default_factory=lambda: ["Default", "English"])
    models: dict[str, list[str]] = field(default_factory=lambda: {})
    notes: dict[int, Note] = field(default_factory=lambda: {})
    media: dict[str, bytes] = field(default_factory=lambda: {})
    calls: list[tuple[str, JsonObject]] = field(default_factory=lambda: [])
    fail_action: str | None = None
    next_id: int = 1500000000000

    def add_note(self, deck: str, model: str, fields: dict[str, str]) -> int:
        for note in self.notes.values():
            first = next(iter(note.fields.values()), "")
            if note.model == model and first == next(iter(fields.values()), ""):
                raise DuplicateNote
        note_id = self.next_id
        self.next_id += 1
        self.notes[note_id] = Note(note_id, model, deck, dict(fields))
        return note_id


class DuplicateNote(Exception):
    pass


class _Handler(BaseHTTPRequestHandler):
    state: FakeAnkiState

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        try:
            decoded = cast(
                JsonValue, json.loads(self.rfile.read(length).decode("utf-8"))
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._reply({"result": None, "error": "invalid request"})
            return
        request = _as_object(decoded)
        action = _as_str(request.get("action"))
        params = _as_object(request.get("params"))
        self.state.calls.append((action, dict(params)))
        if self.state.fail_action == action:
            self._reply({"result": None, "error": f"{action} failed"})
            return
        if _as_int(request.get("version")) != EXPECTED_VERSION:
            self._reply({"result": None, "error": "unsupported version"})
            return
        try:
            self._reply({"result": self._dispatch(action, params), "error": None})
        except DuplicateNote:
            self._reply(
                {
                    "result": None,
                    "error": "cannot create note because it is a duplicate",
                }
            )
        except KeyError as exc:
            self._reply({"result": None, "error": f"unsupported action: {exc}"})

    def _dispatch(self, action: str, params: JsonObject) -> JsonValue:
        state = self.state
        if action == "deckNames":
            return list(state.decks)
        if action == "modelNames":
            return list(state.models)
        if action == "modelFieldNames":
            return list(state.models.get(_as_str(params.get("modelName")), []))
        if action == "createModel":
            name = _as_str(params.get("modelName"))
            state.models[name] = [
                _as_str(item) for item in _as_list(params.get("inOrderFields"))
            ]
            return {"name": name}
        if action == "addField":
            model = _as_str(params.get("modelName"))
            state.models.setdefault(model, []).append(_as_str(params.get("fieldName")))
            return None
        if action == "deleteModel":
            state.models.pop(_as_str(params.get("modelName")), None)
            return None
        if action == "findNotes":
            query = _as_str(params.get("query"))
            return [
                note.note_id for note in state.notes.values() if _matches(note, query)
            ]
        if action == "notesInfo":
            ids = [_as_int(item) for item in _as_list(params.get("notes"))]
            return [
                {
                    "noteId": note.note_id,
                    "modelName": note.model,
                    "tags": [],
                    "fields": {
                        name: {"value": value, "order": index}
                        for index, (name, value) in enumerate(note.fields.items())
                    },
                }
                for note_id in ids
                if (note := state.notes.get(note_id)) is not None
            ]
        if action == "addNote":
            note = _as_object(params.get("note"))
            fields = _as_object(note.get("fields"))
            return state.add_note(
                _as_str(note.get("deckName")),
                _as_str(note.get("modelName")),
                {name: _as_str(value) for name, value in fields.items()},
            )
        if action == "updateNoteFields":
            note = _as_object(params.get("note"))
            target = state.notes.get(_as_int(note.get("id")))
            if target is None:
                raise KeyError("note not found")
            for name, value in _as_object(note.get("fields")).items():
                target.fields[name] = _as_str(value)
            return None
        if action == "storeMediaFile":
            # The client base64-encodes the bytes; it never sends a path.
            filename = _as_str(params.get("filename"))
            state.media[filename] = base64.b64decode(_as_str(params.get("data")))
            return filename
        raise KeyError(action)

    def _reply(self, payload: JsonObject) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_QUERY_TOKEN = re.compile(r'(\w+):"((?:[^"\\]|\\.)*)"|(\w+):(\S+)')


def _matches(note: Note, query: str) -> bool:
    """Anki search syntax, the subset the client emits.

    Queries look like `deck:"English" note:"Translator" word:"bank"`, so the
    quotes must be parsed, not stripped: splitting on whitespace first turns
    `note:"Translator"` into an empty value and matches nothing.
    """
    for match in _QUERY_TOKEN.finditer(query):
        key = match.group(1) or match.group(3)
        value = match.group(2) if match.group(1) else match.group(4)
        value = value.replace('\\"', '"').replace("\\\\", "\\")
        if key == "note":
            if note.model != value:
                return False
        elif key == "deck":
            if note.deck != value:
                return False
        elif note.fields.get(key, "") != value:
            return False
    return True


class FakeAnkiConnect:
    """Serves the protocol on 127.0.0.1 with an ephemeral port."""

    def __init__(self, state: FakeAnkiState | None = None) -> None:
        self.state = state or FakeAnkiState()
        handler: type[_Handler] = type("_Bound", (_Handler,), {"state": self.state})
        self._server = HTTPServer(("127.0.0.1", 0), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeAnkiConnect":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
