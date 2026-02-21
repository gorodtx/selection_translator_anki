from __future__ import annotations

import asyncio
import base64
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp

from desktop_app.infrastructure.anki import (
    AnkiAddResult,
    AnkiClient,
    AnkiCreateModelResult,
    AnkiIdListResult,
    AnkiListResult,
    AnkiNoteDetailsResult,
    AnkiNoteInfoResult,
    AnkiUpdateResult,
)
from desktop_app.infrastructure.services.runtime import AsyncRuntime


@dataclass(frozen=True, slots=True)
class AnkiSchemaResult:
    model: str | None
    fields: list[str]
    error: str | None


def _list_future_set() -> set[Future[AnkiListResult]]:
    return set()


def _pair_future_set() -> set[Future[tuple[AnkiListResult, AnkiListResult]]]:
    return set()


def _add_future_set() -> set[Future[AnkiAddResult]]:
    return set()


def _create_future_set() -> set[Future[AnkiCreateModelResult]]:
    return set()


def _schema_future_set() -> set[Future[AnkiSchemaResult]]:
    return set()


def _id_future_set() -> set[Future[AnkiIdListResult]]:
    return set()


def _details_future_set() -> set[Future[AnkiNoteDetailsResult]]:
    return set()


def _update_future_set() -> set[Future[AnkiUpdateResult]]:
    return set()


@dataclass(slots=True)
class AnkiService:
    runtime: AsyncRuntime
    timeout_seconds: float
    base_url: str

    _session: aiohttp.ClientSession | None = None
    _session_lock: asyncio.Lock | None = None
    _active_list: set[Future[AnkiListResult]] = field(default_factory=_list_future_set)
    _active_pair: set[Future[tuple[AnkiListResult, AnkiListResult]]] = field(
        default_factory=_pair_future_set
    )
    _active_add: set[Future[AnkiAddResult]] = field(default_factory=_add_future_set)
    _active_create: set[Future[AnkiCreateModelResult]] = field(
        default_factory=_create_future_set
    )
    _active_schema: set[Future[AnkiSchemaResult]] = field(
        default_factory=_schema_future_set
    )
    _active_ids: set[Future[AnkiIdListResult]] = field(default_factory=_id_future_set)
    _active_details: set[Future[AnkiNoteDetailsResult]] = field(
        default_factory=_details_future_set
    )
    _active_update: set[Future[AnkiUpdateResult]] = field(
        default_factory=_update_future_set
    )

    def deck_names(self) -> Future[AnkiListResult]:
        future: Future[AnkiListResult] = asyncio.run_coroutine_threadsafe(
            self._deck_names_async(),
            self.runtime.loop,
        )
        return self._register_list_future(future)

    def model_names(self) -> Future[AnkiListResult]:
        future: Future[AnkiListResult] = asyncio.run_coroutine_threadsafe(
            self._model_names_async(),
            self.runtime.loop,
        )
        return self._register_list_future(future)

    def deck_and_model_names(
        self,
    ) -> Future[tuple[AnkiListResult, AnkiListResult]]:
        future: Future[tuple[AnkiListResult, AnkiListResult]] = (
            asyncio.run_coroutine_threadsafe(
                self._deck_and_model_names_async(),
                self.runtime.loop,
            )
        )
        return self._register_pair_future(future)

    def model_field_names(self, model: str) -> Future[AnkiListResult]:
        future: Future[AnkiListResult] = asyncio.run_coroutine_threadsafe(
            self._model_field_names_async(model),
            self.runtime.loop,
        )
        return self._register_list_future(future)

    def find_notes(self, query: str) -> Future[AnkiIdListResult]:
        future: Future[AnkiIdListResult] = asyncio.run_coroutine_threadsafe(
            self._find_notes_async(query),
            self.runtime.loop,
        )
        return self._register_id_future(future)

    def note_details(self, note_ids: list[int]) -> Future[AnkiNoteDetailsResult]:
        future: Future[AnkiNoteDetailsResult] = asyncio.run_coroutine_threadsafe(
            self._note_details_async(note_ids),
            self.runtime.loop,
        )
        return self._register_details_future(future)

    def deck_schema(self, deck: str) -> Future[AnkiSchemaResult]:
        future: Future[AnkiSchemaResult] = asyncio.run_coroutine_threadsafe(
            self._deck_schema_async(deck),
            self.runtime.loop,
        )
        return self._register_schema_future(future)

    def add_note(
        self, deck: str, model: str, fields: dict[str, str]
    ) -> Future[AnkiAddResult]:
        future: Future[AnkiAddResult] = asyncio.run_coroutine_threadsafe(
            self._add_note_async(deck, model, fields),
            self.runtime.loop,
        )
        return self._register_add_future(future)

    def update_note_fields(
        self, note_id: int, fields: dict[str, str]
    ) -> Future[AnkiUpdateResult]:
        future: Future[AnkiUpdateResult] = asyncio.run_coroutine_threadsafe(
            self._update_note_fields_async(note_id, fields),
            self.runtime.loop,
        )
        return self._register_update_future(future)

    def store_media_path(self, local_path: str, filename: str) -> Future[AnkiUpdateResult]:
        future: Future[AnkiUpdateResult] = asyncio.run_coroutine_threadsafe(
            self._store_media_path_async(local_path, filename),
            self.runtime.loop,
        )
        return self._register_update_future(future)

    def add_field(self, model: str, field_name: str) -> Future[AnkiUpdateResult]:
        future: Future[AnkiUpdateResult] = asyncio.run_coroutine_threadsafe(
            self._add_field_async(model, field_name),
            self.runtime.loop,
        )
        return self._register_update_future(future)

    def delete_model(self, model: str) -> Future[AnkiUpdateResult]:
        future: Future[AnkiUpdateResult] = asyncio.run_coroutine_threadsafe(
            self._delete_model_async(model),
            self.runtime.loop,
        )
        return self._register_update_future(future)

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]:
        future: Future[AnkiCreateModelResult] = asyncio.run_coroutine_threadsafe(
            self._create_model_async(model_name, fields, front, back, css),
            self.runtime.loop,
        )
        return self._register_create_future(future)

    def cancel_active(self) -> None:
        for list_future in list(self._active_list):
            list_future.cancel()
        for pair_future in list(self._active_pair):
            pair_future.cancel()
        for add_future in list(self._active_add):
            add_future.cancel()
        for create_future in list(self._active_create):
            create_future.cancel()
        for schema_future in list(self._active_schema):
            schema_future.cancel()
        for id_future in list(self._active_ids):
            id_future.cancel()
        for details_future in list(self._active_details):
            details_future.cancel()
        for update_future in list(self._active_update):
            update_future.cancel()
        self._active_list.clear()
        self._active_pair.clear()
        self._active_add.clear()
        self._active_create.clear()
        self._active_schema.clear()
        self._active_ids.clear()
        self._active_details.clear()
        self._active_update.clear()
        asyncio.run_coroutine_threadsafe(self._abort_session(), self.runtime.loop)

    async def close(self) -> None:
        await self._abort_session()

    def _register_list_future(
        self, future: Future[AnkiListResult]
    ) -> Future[AnkiListResult]:
        self._active_list.add(future)
        future.add_done_callback(self._active_list.discard)
        return future

    def _register_pair_future(
        self, future: Future[tuple[AnkiListResult, AnkiListResult]]
    ) -> Future[tuple[AnkiListResult, AnkiListResult]]:
        self._active_pair.add(future)
        future.add_done_callback(self._active_pair.discard)
        return future

    def _register_add_future(
        self, future: Future[AnkiAddResult]
    ) -> Future[AnkiAddResult]:
        self._active_add.add(future)
        future.add_done_callback(self._active_add.discard)
        return future

    def _register_create_future(
        self, future: Future[AnkiCreateModelResult]
    ) -> Future[AnkiCreateModelResult]:
        self._active_create.add(future)
        future.add_done_callback(self._active_create.discard)
        return future

    def _register_schema_future(
        self, future: Future[AnkiSchemaResult]
    ) -> Future[AnkiSchemaResult]:
        self._active_schema.add(future)
        future.add_done_callback(self._active_schema.discard)
        return future

    def _register_id_future(
        self, future: Future[AnkiIdListResult]
    ) -> Future[AnkiIdListResult]:
        self._active_ids.add(future)
        future.add_done_callback(self._active_ids.discard)
        return future

    def _register_details_future(
        self, future: Future[AnkiNoteDetailsResult]
    ) -> Future[AnkiNoteDetailsResult]:
        self._active_details.add(future)
        future.add_done_callback(self._active_details.discard)
        return future

    def _register_update_future(
        self, future: Future[AnkiUpdateResult]
    ) -> Future[AnkiUpdateResult]:
        self._active_update.add(future)
        future.add_done_callback(self._active_update.discard)
        return future

    async def _deck_names_async(self) -> AnkiListResult:
        client = await self._ensure_client()
        return await client.deck_names()

    async def _model_names_async(self) -> AnkiListResult:
        client = await self._ensure_client()
        return await client.model_names()

    async def _deck_and_model_names_async(
        self,
    ) -> tuple[AnkiListResult, AnkiListResult]:
        client = await self._ensure_client()
        deck_task = asyncio.create_task(client.deck_names())
        model_task = asyncio.create_task(client.model_names())
        deck_result, model_result = await asyncio.gather(deck_task, model_task)
        return deck_result, model_result

    async def _model_field_names_async(self, model: str) -> AnkiListResult:
        client = await self._ensure_client()
        return await client.model_field_names(model)

    async def _find_notes_async(self, query: str) -> AnkiIdListResult:
        client = await self._ensure_client()
        return await client.find_notes(query)

    async def _note_details_async(self, note_ids: list[int]) -> AnkiNoteDetailsResult:
        client = await self._ensure_client()
        return await client.note_details(note_ids)

    async def _deck_schema_async(self, deck: str) -> AnkiSchemaResult:
        client = await self._ensure_client()
        note_ids = await self._find_notes_for_deck(client, deck)
        if note_ids.error is not None:
            return AnkiSchemaResult(model=None, fields=[], error=note_ids.error)
        info_result = await self._note_info(client, note_ids.items[:1])
        if info_result.error is not None:
            return AnkiSchemaResult(model=None, fields=[], error=info_result.error)
        info = info_result.info
        if info is None:
            return AnkiSchemaResult(
                model=None,
                fields=[],
                error="Invalid AnkiConnect response",
            )
        return AnkiSchemaResult(model=info.model, fields=info.fields, error=None)

    async def _add_note_async(
        self, deck: str, model: str, fields: dict[str, str]
    ) -> AnkiAddResult:
        client = await self._ensure_client()
        return await client.add_note(deck, model, fields)

    async def _update_note_fields_async(
        self, note_id: int, fields: dict[str, str]
    ) -> AnkiUpdateResult:
        client = await self._ensure_client()
        return await client.update_note_fields(note_id, fields)

    async def _store_media_path_async(
        self, local_path: str, filename: str
    ) -> AnkiUpdateResult:
        client = await self._ensure_client()
        try:
            raw = await asyncio.to_thread(_read_binary_file, local_path)
        except OSError as exc:
            return AnkiUpdateResult(success=False, error=f"Failed to read image: {exc}")
        payload = base64.b64encode(raw).decode("ascii")
        return await client.store_media_file(filename, payload)

    async def _add_field_async(self, model: str, field_name: str) -> AnkiUpdateResult:
        client = await self._ensure_client()
        return await client.add_field(model, field_name)

    async def _delete_model_async(self, model: str) -> AnkiUpdateResult:
        client = await self._ensure_client()
        return await client.delete_model(model)

    async def _create_model_async(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> AnkiCreateModelResult:
        client = await self._ensure_client()
        return await client.create_model(model_name, fields, front, back, css)

    async def _find_notes_for_deck(
        self, client: AnkiClient, deck: str
    ) -> AnkiIdListResult:
        deck_name = deck.replace('"', '\\"')
        return await client.find_notes(f'deck:"{deck_name}"')

    async def _note_info(
        self, client: AnkiClient, note_ids: list[int]
    ) -> AnkiNoteInfoResult:
        return await client.notes_info(note_ids)

    async def _ensure_client(self) -> AnkiClient:
        if self._session is not None:
            return AnkiClient(
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
                session=self._session,
            )
        lock = self._session_lock
        if lock is None:
            lock = asyncio.Lock()
            self._session_lock = lock
        async with lock:
            if self._session is None:
                self._session = aiohttp.ClientSession()
            return AnkiClient(
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
                session=self._session,
            )

    async def _abort_session(self) -> None:
        if self._session is None:
            return
        await self._session.close()
        self._session = None


def _read_binary_file(path: str) -> bytes:
    return Path(path).read_bytes()
