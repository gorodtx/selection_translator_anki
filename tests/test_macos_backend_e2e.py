"""End-to-end coverage for the macOS backend over a real Unix socket.

These tests start the daemon in-process (no subprocess, no network, no Anki)
and drive it through the wire protocol exactly as the SwiftUI shell does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from typing import cast

import pytest

from desktop_app.application.dispatch import call_inline
from desktop_app.application.use_cases.anki_flow import AnkiFlow
from desktop_app.application.use_cases.translation_flow import TranslationFlow
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig, LanguageConfig
from desktop_app.infrastructure.services.container import AppServices
from desktop_app.infrastructure.services.history import HistoryStore
from desktop_app.infrastructure.services.runtime import AsyncRuntime
from desktop_app.platform.macos.daemon import BackendApi, db_status
from desktop_app.platform.macos.ipc import protocol
from desktop_app.platform.macos.ipc.protocol import (
    Event,
    JsonObject,
    Request,
    encode_line,
)
from desktop_app.platform.macos.ipc.server import MAX_SOCKET_PATH_BYTES, IpcServer
from desktop_app.platform.macos.session import BackendSession
from desktop_app.platform import paths
from translate_logic.infrastructure.language_base import locations
from translate_logic.models import Example, FieldValue, TranslationResult

RESULT = TranslationResult(
    translation_ru=FieldValue.present("банк"),
    definitions_en=("A financial institution.",),
    examples=(Example("The bank is closed."), Example("He robbed a bank.")),
)


@dataclass(slots=True)
class _Translator:
    calls: list[str] = field(default_factory=lambda: [])

    def get_cached(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult | None:
        del text, source_lang, target_lang
        return None

    def translate(
        self,
        text: str,
        lookup_text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]:
        del lookup_text, source_lang, target_lang
        self.calls.append(text)
        if on_partial is not None:
            on_partial(TranslationResult(translation_ru=FieldValue.present("банк")))
        future: Future[TranslationResult] = Future()
        future.set_result(RESULT)
        return future

    def refresh_examples(
        self, lookup_text: str, *, limit: int
    ) -> Future[tuple[Example, ...]]:
        del lookup_text, limit
        future: Future[tuple[Example, ...]] = Future()
        future.set_result((Example("A river bank at dawn."),))
        return future


class _NoAnki:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"anki must not be reached ({name})")


@dataclass(slots=True)
class _Services:
    translation_flow: TranslationFlow
    anki_flow: AnkiFlow
    runtime: AsyncRuntime

    def cancel_active(self) -> None:
        return None


def _config() -> AppConfig:
    return AppConfig(
        languages=LanguageConfig(source="en", target="ru"),
        anki=AnkiConfig(deck="", model="", fields=AnkiFieldMap("", "", "", "", "")),
    )


def _socket_path() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="tr-e2e-"))
    path = directory / "b.sock"
    if len(str(path).encode("utf-8")) > MAX_SOCKET_PATH_BYTES:
        pytest.skip("temporary directory too long for AF_UNIX sockets")
    return path


class _Client:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._events: list[JsonObject] = []
        self._next = 1

    @property
    def events(self) -> list[JsonObject]:
        return self._events

    async def call(self, method: str, **params: object) -> JsonObject:
        request_id = self._next
        self._next += 1
        self._writer.write(
            encode_line(
                {"id": request_id, "method": method, "params": cast(JsonObject, params)}
            )
        )
        await self._writer.drain()
        while True:
            line = await asyncio.wait_for(self._reader.readline(), 10)
            assert line, "backend closed the connection"
            message = protocol.as_json_object(json.loads(line.decode("utf-8")))
            assert message is not None
            if message.get("id") == request_id:
                return message
            if "event" in message:
                self._events.append(message)

    def phases(self) -> list[str]:
        phases: list[str] = []
        for message in self._events:
            if message.get("event") != str(Event.TRANSLATION_STATE):
                continue
            payload = protocol.as_json_object(message.get("payload"))
            assert payload is not None
            phases.append(str(payload["phase"]))
        return phases


async def _run(scenario: Callable[[_Client], object]) -> None:
    socket_path = _socket_path()
    translator = _Translator()
    services = _Services(
        translation_flow=TranslationFlow(translator=translator, history=HistoryStore()),
        anki_flow=AnkiFlow(service=cast("object", _NoAnki())),  # type: ignore[arg-type]
        runtime=AsyncRuntime(),
    )
    server_box: list[IpcServer] = []
    session = BackendSession(
        services=cast(AppServices, services),
        config=_config(),
        dispatch=call_inline,
        emit=lambda event, payload: server_box[0].broadcast(event, payload),
        save_config=lambda config: None,
    )
    api = BackendApi(
        session=session,
        loop=asyncio.get_running_loop(),
        socket_path=socket_path,
        request_shutdown=lambda: None,
        engines=lambda: {"apple_dictionary": False, "apple_translation": False},
    )
    server = IpcServer(socket_path=socket_path, handler=api.handle)
    server_box.append(server)
    await server.start()
    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
    try:
        result = scenario(_Client(reader, writer))
        if asyncio.iscoroutine(result):
            await result
    finally:
        writer.close()
        await server.stop()


def test_full_translate_flow_over_the_socket() -> None:
    async def scenario(client: _Client) -> None:
        ping = await client.call("ping")
        result = protocol.as_json_object(ping["result"])
        assert result is not None
        assert result["protocol"] == protocol.PROTOCOL_VERSION
        assert result["socket"].__class__ is str

        response = await client.call("translate", text="bank")
        assert response["ok"] is True
        body = protocol.as_json_object(response["result"])
        assert body is not None
        state = protocol.as_json_object(body["state"])
        assert state is not None
        assert state["translation_raw"] == "банк"
        assert state["loading"] is False
        assert state["can_add_anki"] is True
        assert state["examples"] == [
            {"en": "The bank is closed."},
            {"en": "He robbed a bank."},
        ]

        history = await client.call("history.list")
        items = protocol.as_json_object(history["result"])
        assert items is not None
        entries = items["items"]
        assert isinstance(entries, list) and len(entries) == 1
        entry = protocol.as_json_object(entries[0])
        assert entry is not None
        assert entry["text"] == "bank"
        assert entry["translation"] == "банк"

        copied = await client.call("copy_all")
        copy_body = protocol.as_json_object(copied["result"])
        assert copy_body is not None
        text = copy_body["text"]
        assert isinstance(text, str)
        assert text.splitlines()[0] == "Original: bank"

        refreshed = await client.call("examples.refresh")
        refresh_body = protocol.as_json_object(refreshed["result"])
        assert refresh_body is not None
        assert refresh_body["changed"] is True

        # begin + partial + final for translate, then two examples phases.
        assert client.phases()[:3] == ["begin", "partial", "final"]
        assert "examples" in client.phases()

    asyncio.run(_run(scenario))


def test_history_select_restores_a_previous_entry() -> None:
    async def scenario(client: _Client) -> None:
        await client.call("translate", text="bank")
        history = await client.call("history.list")
        body = protocol.as_json_object(history["result"])
        assert body is not None
        entries = body["items"]
        assert isinstance(entries, list)
        entry = protocol.as_json_object(entries[0])
        assert entry is not None
        entry_id = entry["entry_id"]

        selected = await client.call("history.select", entry_id=entry_id)
        assert selected["ok"] is True
        selected_body = protocol.as_json_object(selected["result"])
        assert selected_body is not None
        state = protocol.as_json_object(selected_body["state"])
        assert state is not None
        assert state["entry_id"] == entry_id
        assert state["translation_raw"] == "банк"

        missing = await client.call("history.select", entry_id=9999)
        assert missing["ok"] is False
        error = protocol.as_json_object(missing["error"])
        assert error is not None
        assert error["code"] == "no_active_entry"

    asyncio.run(_run(scenario))


def test_settings_roundtrip_and_error_shapes() -> None:
    async def scenario(client: _Client) -> None:
        settings = await client.call("settings.get")
        config = protocol.as_json_object(settings["result"])
        assert config is not None
        languages = protocol.as_json_object(config["languages"])
        assert languages == {"source": "en", "target": "ru"}

        unknown = await client.call("nope")
        assert unknown["ok"] is False
        error = protocol.as_json_object(unknown["error"])
        assert error is not None
        assert error["code"] == "unknown_method"

        bad = await client.call("translate")
        assert bad["ok"] is False
        bad_error = protocol.as_json_object(bad["error"])
        assert bad_error is not None
        assert bad_error["code"] == "invalid_params"

        no_entry = await client.call("copy_all")
        assert no_entry["ok"] is False
        no_entry_error = protocol.as_json_object(no_entry["error"])
        assert no_entry_error is not None
        assert no_entry_error["code"] == "no_active_entry"

    asyncio.run(_run(scenario))


def test_cancel_and_close_are_idempotent() -> None:
    async def scenario(client: _Client) -> None:
        await client.call("translate", text="bank")
        for method in ("cancel", "close", "cancel"):
            response = await client.call(method)
            assert response["ok"] is True
            assert protocol.as_json_object(response["result"]) == {}
        # History survives cancellation.
        history = await client.call("history.list")
        body = protocol.as_json_object(history["result"])
        assert body is not None
        assert isinstance(body["items"], list) and body["items"]

    asyncio.run(_run(scenario))


def test_db_status_reports_the_directory_the_bases_resolved_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "db"
    override.mkdir()
    monkeypatch.setenv("TRANSLATOR_DB_DIR", str(override))
    monkeypatch.setattr(locations, "offline_base_dir_candidates", lambda: (override,))
    (override / "primary.sqlite3").write_bytes(b"x")

    status = db_status()

    assert status["primary"] is True
    assert status["fallback"] is False
    assert status["definitions"] is False
    assert status["dir"] == str(override)


def test_db_status_points_at_the_real_location_not_the_download_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An override directory that is empty must not make the UI claim the bases
    # live there when they were actually found elsewhere.
    download_dir = tmp_path / "empty"
    real_dir = tmp_path / "real"
    download_dir.mkdir()
    real_dir.mkdir()
    (real_dir / "primary.sqlite3").write_bytes(b"x")
    monkeypatch.setattr(paths, "db_dir", lambda: download_dir)
    monkeypatch.setattr(
        locations, "offline_base_dir_candidates", lambda: (download_dir, real_dir)
    )

    status = db_status()

    assert status["primary"] is True
    assert status["dir"] == str(real_dir)


def test_server_rejects_socket_paths_longer_than_af_unix_allows(tmp_path: Path) -> None:
    long_path = tmp_path / ("a" * 120) / "b.sock"

    async def scenario() -> None:
        server = IpcServer(socket_path=long_path, handler=_unused_handler)
        with pytest.raises(RuntimeError, match="AF_UNIX allows at most"):
            await server.start()

    asyncio.run(scenario())


async def _unused_handler(request: Request) -> JsonObject:
    raise AssertionError(f"handler must not run ({request.method})")


def test_second_backend_never_removes_the_running_socket() -> None:
    """A refused start must leave the live instance serving."""

    async def scenario() -> None:
        socket_path = _socket_path()

        async def handler(request: Request) -> JsonObject:
            return {"echo": request.method}

        first = IpcServer(socket_path=socket_path, handler=handler)
        await first.start()
        try:
            second = IpcServer(socket_path=socket_path, handler=handler)
            with pytest.raises(RuntimeError, match="already listening"):
                await second.start()
            # The losing instance still runs its shutdown path.
            await second.stop()

            assert socket_path.exists(), "the live socket was removed"
            reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
            try:
                writer.write(encode_line({"id": 1, "method": "ping"}))
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), 5)
                message = protocol.as_json_object(json.loads(line.decode("utf-8")))
                assert message is not None and message["ok"] is True
            finally:
                writer.close()
        finally:
            await first.stop()
        assert not socket_path.exists()

    asyncio.run(scenario())
