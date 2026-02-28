from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal, cast

PipeCommandName = Literal[
    "translate",
    "show_settings",
    "show_history",
    "get_anki_status",
    "ping",
]
PipeResponseStatus = Literal["ok", "error"]

_COMMAND_NAMES: set[str] = {
    "translate",
    "show_settings",
    "show_history",
    "get_anki_status",
    "ping",
}
_RESPONSE_STATUSES: set[str] = {"ok", "error"}


@dataclass(frozen=True, slots=True)
class PipeCommand:
    name: PipeCommandName
    text: str = ""


@dataclass(frozen=True, slots=True)
class PipeResponse:
    status: PipeResponseStatus
    message: str = ""
    payload: dict[str, str] | None = None


def encode_command(command: PipeCommand) -> bytes:
    payload: dict[str, object] = {"name": command.name}
    if command.name == "translate":
        payload["text"] = command.text
    return _encode_payload(payload)


def decode_command(raw: bytes) -> PipeCommand:
    payload = _decode_payload(raw)
    name_raw = payload.get("name")
    if not isinstance(name_raw, str) or name_raw not in _COMMAND_NAMES:
        raise ValueError("Invalid command name.")
    name = cast(PipeCommandName, name_raw)
    if name_raw == "translate":
        text_raw = payload.get("text")
        if not isinstance(text_raw, str):
            raise ValueError("Translate command requires a text string.")
        return PipeCommand(name="translate", text=text_raw)
    return PipeCommand(name=name)


def encode_response(response: PipeResponse) -> bytes:
    payload: dict[str, object] = {
        "status": response.status,
        "message": response.message,
    }
    if response.payload is not None:
        payload["payload"] = response.payload
    return _encode_payload(payload)


def decode_response(raw: bytes) -> PipeResponse:
    payload = _decode_payload(raw)
    status_raw = payload.get("status")
    if not isinstance(status_raw, str) or status_raw not in _RESPONSE_STATUSES:
        raise ValueError("Invalid response status.")
    status = cast(PipeResponseStatus, status_raw)
    message_raw = payload.get("message", "")
    if not isinstance(message_raw, str):
        raise ValueError("Invalid response message.")
    payload_raw = payload.get("payload")
    if payload_raw is None:
        return PipeResponse(status=status, message=message_raw, payload=None)
    if not isinstance(payload_raw, dict):
        raise ValueError("Invalid response payload.")
    validated: dict[str, str] = {}
    for key, value in payload_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Invalid response payload value.")
        validated[key] = value
    return PipeResponse(status=status, message=message_raw, payload=validated)


def _decode_payload(raw: bytes) -> dict[str, object]:
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON payload.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON payload type.")
    return payload


def _encode_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
