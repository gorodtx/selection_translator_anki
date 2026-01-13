from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Final, TypeGuard
import aiohttp

ANKI_CONNECT_URL: Final[str] = "http://127.0.0.1:8765"
ANKI_CONNECT_VERSION: Final[int] = 6
DEFAULT_TIMEOUT_SECONDS: Final[float] = 3.0


@dataclass(frozen=True, slots=True)
class AnkiResponse:
    result: object | None
    error: str | None


@dataclass(frozen=True, slots=True)
class AnkiListResult:
    items: list[str]
    error: str | None


@dataclass(frozen=True, slots=True)
class AnkiIdListResult:
    items: list[int]
    error: str | None


@dataclass(frozen=True, slots=True)
class AnkiNoteInfo:
    model: str
    fields: list[str]


@dataclass(frozen=True, slots=True)
class AnkiNoteInfoResult:
    info: AnkiNoteInfo | None
    error: str | None


@dataclass(frozen=True, slots=True)
class AnkiAddResult:
    success: bool
    error: str | None
    note_id: int | None


@dataclass(frozen=True, slots=True)
class AnkiCreateModelResult:
    success: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class AnkiClient:
    base_url: str = ANKI_CONNECT_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    session: aiohttp.ClientSession | None = None

    async def deck_names(self) -> AnkiListResult:
        response = await self._request("deckNames", None)
        return _coerce_list_response(response)

    async def model_names(self) -> AnkiListResult:
        response = await self._request("modelNames", None)
        return _coerce_list_response(response)

    async def model_field_names(self, model: str) -> AnkiListResult:
        response = await self._request("modelFieldNames", {"modelName": model})
        return _coerce_list_response(response)

    async def find_notes(self, query: str) -> AnkiIdListResult:
        response = await self._request("findNotes", {"query": query})
        return _coerce_id_list_response(response)

    async def notes_info(self, note_ids: list[int]) -> AnkiNoteInfoResult:
        if not note_ids:
            return AnkiNoteInfoResult(info=None, error="No notes found.")
        response = await self._request("notesInfo", {"notes": note_ids})
        return _coerce_note_info(response)

    async def add_note(
        self,
        deck: str,
        model: str,
        fields: dict[str, str],
    ) -> AnkiAddResult:
        payload: dict[str, object] = {
            "deckName": deck,
            "modelName": model,
            "fields": fields,
        }
        response = await self._request("addNote", {"note": payload})
        if response.error is not None:
            return AnkiAddResult(success=False, error=response.error, note_id=None)
        note_id = _coerce_int(response.result)
        if note_id is None:
            return AnkiAddResult(
                success=False,
                error="Invalid AnkiConnect response",
                note_id=None,
            )
        return AnkiAddResult(success=True, error=None, note_id=note_id)

    async def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> AnkiCreateModelResult:
        payload: dict[str, object] = {
            "modelName": model_name,
            "inOrderFields": fields,
            "css": css,
            "cardTemplates": [
                {"Name": "Card 1", "Front": front, "Back": back},
            ],
        }
        response = await self._request("createModel", payload)
        if response.error is not None:
            return AnkiCreateModelResult(success=False, error=response.error)
        return AnkiCreateModelResult(success=True, error=None)

    async def _request(
        self, action: str, params: dict[str, object] | None
    ) -> AnkiResponse:
        payload: dict[str, object] = {
            "action": action,
            "version": ANKI_CONNECT_VERSION,
        }
        if params is not None:
            payload["params"] = params
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            if self.session is None:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.base_url, json=payload) as response:
                        raw_payload = await response.text()
            else:
                async with self.session.post(
                    self.base_url, json=payload, timeout=timeout
                ) as response:
                    raw_payload = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            return AnkiResponse(result=None, error=f"AnkiConnect error: {exc}")
        return _parse_response(raw_payload)


def _parse_response(payload: str) -> AnkiResponse:
    try:
        data: object = json.loads(payload)
    except json.JSONDecodeError:
        return AnkiResponse(result=None, error="Invalid AnkiConnect response")
    data_dict = _coerce_dict(data)
    if data_dict is None:
        return AnkiResponse(result=None, error="Invalid AnkiConnect response")
    error = _coerce_str(data_dict.get("error"))
    return AnkiResponse(result=data_dict.get("result"), error=error)


def _coerce_list_response(response: AnkiResponse) -> AnkiListResult:
    if response.error is not None:
        return AnkiListResult(items=[], error=response.error)
    items = _coerce_str_list(response.result)
    if not items and response.result is not None:
        return AnkiListResult(items=[], error="Invalid AnkiConnect response")
    return AnkiListResult(items=items, error=None)


def _coerce_id_list_response(response: AnkiResponse) -> AnkiIdListResult:
    if response.error is not None:
        return AnkiIdListResult(items=[], error=response.error)
    items = _coerce_int_list(response.result)
    if not items and response.result is not None:
        return AnkiIdListResult(items=[], error="Invalid AnkiConnect response")
    return AnkiIdListResult(items=items, error=None)


def _coerce_note_info(response: AnkiResponse) -> AnkiNoteInfoResult:
    if response.error is not None:
        return AnkiNoteInfoResult(info=None, error=response.error)
    result_list = _coerce_list(response.result)
    if result_list is None or not result_list:
        return AnkiNoteInfoResult(info=None, error="Invalid AnkiConnect response")
    first = result_list[0]
    first_dict = _coerce_dict(first)
    if first_dict is None:
        return AnkiNoteInfoResult(info=None, error="Invalid AnkiConnect response")
    model = _coerce_str(first_dict.get("modelName"))
    fields_raw = _coerce_dict(first_dict.get("fields"))
    if model is None or fields_raw is None:
        return AnkiNoteInfoResult(info=None, error="Invalid AnkiConnect response")
    fields = [key for key in fields_raw.keys()]
    if not fields:
        return AnkiNoteInfoResult(info=None, error="Invalid AnkiConnect response")
    return AnkiNoteInfoResult(info=AnkiNoteInfo(model=model, fields=fields), error=None)


def _coerce_str_list(value: object | None) -> list[str]:
    value_list = _coerce_list(value)
    if value_list is None:
        return []
    items: list[str] = []
    for raw_item in value_list:
        if isinstance(raw_item, str):
            items.append(raw_item)
    return items


def _coerce_int_list(value: object | None) -> list[int]:
    value_list = _coerce_list(value)
    if value_list is None:
        return []
    items: list[int] = []
    for raw_item in value_list:
        if isinstance(raw_item, int):
            items.append(raw_item)
    return items


def _coerce_dict(value: object | None) -> dict[str, object] | None:
    if not _is_str_dict(value):
        return None
    return dict(value)


def _coerce_list(value: object | None) -> list[object] | None:
    if not _is_object_list(value):
        return None
    return list(value)


def _coerce_str(value: object | None) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _coerce_int(value: object | None) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _is_str_dict(value: object | None) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object | None) -> TypeGuard[list[object]]:
    return isinstance(value, list)
