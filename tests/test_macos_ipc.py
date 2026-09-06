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
from desktop_app.application.use_cases.anki_upsert import (
    AnkiFieldAction,
    AnkiImageAction,
)
from desktop_app.application.use_cases.translation_flow import TranslationFlow
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig, LanguageConfig
from desktop_app.infrastructure.services.container import AppServices
from desktop_app.infrastructure.services.history import HistoryStore
from desktop_app.infrastructure.services.runtime import AsyncRuntime
from desktop_app.platform.macos.daemon import BackendApi
from desktop_app.platform.macos.ipc import protocol
from desktop_app.platform.macos.ipc.protocol import (
    ErrorCode,
    Event,
    JsonObject,
    Phase,
    ProtocolDecodeError,
    Request,
    anki_decision_from_json,
    decode_request,
    encode_line,
)
from desktop_app.platform.macos.ipc.server import IpcServer
from desktop_app.platform.macos.session import BackendSession, SessionError
from translate_logic.models import Example, FieldValue, TranslationResult

# --- protocol ------------------------------------------------------------------


def test_decode_request_roundtrip() -> None:
    line = encode_line({"id": 7, "method": "translate", "params": {"text": "time"}})

    request = decode_request(line)

    assert request == Request(id=7, method="translate", params={"text": "time"})


def test_decode_request_defaults_params_and_accepts_string_ids() -> None:
    request = decode_request('{"id": "abc", "method": "ping"}')

    assert request.id == "abc"
    assert request.params == {}


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[1, 2]",
        '{"method": "ping"}',
        '{"id": true, "method": "ping"}',
        '{"id": 1}',
        '{"id": 1, "method": "ping", "params": []}',
    ],
)
def test_decode_request_rejects_malformed_input(raw: str) -> None:
    with pytest.raises(ProtocolDecodeError):
        decode_request(raw)


def test_anki_decision_from_json_uses_safe_defaults() -> None:
    decision = anki_decision_from_json({"create_new": True})

    assert decision.create_new is True
    assert decision.target_note_ids == ()
    assert decision.translation_action is AnkiFieldAction.KEEP_EXISTING
    assert decision.image_action is AnkiImageAction.KEEP_EXISTING
    assert decision.image_path is None


def test_anki_decision_from_json_rejects_unknown_action() -> None:
    with pytest.raises(ProtocolDecodeError) as excinfo:
        anki_decision_from_json({"translation_action": "explode"})

    assert excinfo.value.code is ErrorCode.INVALID_PARAMS


# --- server ----------------------------------------------------------------------


def _read_json(line: bytes) -> JsonObject:
    payload = protocol.as_json_object(json.loads(line.decode("utf-8")))
    assert payload is not None
    return payload


def _short_socket_path() -> Path:
    # pytest's tmp_path can exceed the 104-byte AF_UNIX limit on macOS.
    directory = Path(tempfile.mkdtemp(prefix="tr-ipc-"))
    path = directory / "t.sock"
    if len(str(path).encode("utf-8")) > 100:
        pytest.skip("temporary directory too long for AF_UNIX sockets")
    return path


def test_server_answers_requests_and_broadcasts_events() -> None:
    socket_path = _short_socket_path()

    async def handler(request: Request) -> JsonObject:
        if request.method == "boom":
            raise RuntimeError("kaboom")
        return {"echo": request.method, "params": request.params}

    async def scenario() -> None:
        server = IpcServer(socket_path=socket_path, handler=handler)
        await server.start()
        reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
        try:
            writer.write(encode_line({"id": 1, "method": "ping", "params": {"a": 1}}))
            await writer.drain()
            response = _read_json(await reader.readline())
            assert response == {
                "id": 1,
                "ok": True,
                "result": {"echo": "ping", "params": {"a": 1}},
            }

            writer.write(b"garbage\n")
            await writer.drain()
            error = _read_json(await reader.readline())
            assert error["ok"] is False
            error_body = protocol.as_json_object(error["error"])
            assert error_body is not None
            assert error_body["code"] == "bad_request"

            writer.write(encode_line({"id": 2, "method": "boom"}))
            await writer.drain()
            failure = _read_json(await reader.readline())
            assert failure["id"] == 2 and failure["ok"] is False
            failure_body = protocol.as_json_object(failure["error"])
            assert failure_body is not None
            assert failure_body["code"] == "internal"

            await asyncio.sleep(0)
            assert server.client_count == 1
            server.broadcast(Event.NOTIFICATION, {"message": "hi", "level": "info"})
            event = _read_json(await reader.readline())
            assert event == {
                "event": "notification",
                "payload": {"message": "hi", "level": "info"},
            }
        finally:
            writer.close()
            await server.stop()
        assert not socket_path.exists()

    asyncio.run(scenario())


# --- session -----------------------------------------------------------------------


def _result(translation: str, *examples: str) -> TranslationResult:
    return TranslationResult(
        translation_ru=FieldValue.present(translation),
        definitions_en=("to search for information",),
        examples=tuple(Example(en=example) for example in examples),
    )


@dataclass(slots=True)
class _FakeTranslator:
    final: TranslationResult
    partial: TranslationResult | None = None
    refresh_pool: tuple[Example, ...] = ()
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
        if self.partial is not None and on_partial is not None:
            on_partial(self.partial)
        future: Future[TranslationResult] = Future()
        future.set_result(self.final)
        return future

    def refresh_examples(
        self, lookup_text: str, *, limit: int
    ) -> Future[tuple[Example, ...]]:
        del lookup_text, limit
        future: Future[tuple[Example, ...]] = Future()
        future.set_result(self.refresh_pool)
        return future


class _UnusedAnkiService:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"anki service must not be used in this test ({name})")


@dataclass(slots=True)
class _FakeServices:
    translation_flow: TranslationFlow
    anki_flow: AnkiFlow
    runtime: AsyncRuntime
    cancelled: int = 0

    def cancel_active(self) -> None:
        self.cancelled += 1


def _config() -> AppConfig:
    return AppConfig(
        languages=LanguageConfig(source="en", target="ru"),
        anki=AnkiConfig(deck="", model="", fields=AnkiFieldMap("", "", "", "", "")),
    )


def _build_session(
    translator: _FakeTranslator,
) -> tuple[BackendSession, list[tuple[Event, JsonObject]], _FakeServices]:
    services = _FakeServices(
        translation_flow=TranslationFlow(translator=translator, history=HistoryStore()),
        anki_flow=AnkiFlow(service=cast("object", _UnusedAnkiService())),  # type: ignore[arg-type]
        runtime=AsyncRuntime(),
    )
    events: list[tuple[Event, JsonObject]] = []
    session = BackendSession(
        services=cast(AppServices, services),
        config=_config(),
        dispatch=call_inline,
        emit=lambda event, payload: events.append((event, payload)),
        save_config=lambda config: None,
    )
    return session, events, services


def _phases(events: list[tuple[Event, JsonObject]]) -> list[str]:
    return [
        str(payload["phase"])
        for event, payload in events
        if event is Event.TRANSLATION_STATE
    ]


def test_session_translate_emits_begin_partial_final_and_records_history() -> None:
    translator = _FakeTranslator(
        final=_result("искать", "Look it up.", "Look up the word."),
        partial=_result("искать"),
    )
    session, events, services = _build_session(translator)

    snapshot = session.translate("look up")

    # cancel() invalidates the previous request before a new id is issued,
    # matching the GNOME controller, so ids advance by two per translation.
    assert snapshot.request_id == session.snapshot().request_id == 2
    assert _phases(events) == [Phase.BEGIN, Phase.PARTIAL, Phase.FINAL]
    final_state = protocol.as_json_object(events[-1][1]["state"])
    assert final_state is not None
    assert final_state["translation"] == "искать"
    assert final_state["loading"] is False
    assert final_state["can_add_anki"] is True
    assert final_state["can_refresh_examples"] is True
    assert final_state["entry_id"] == 1
    assert [item.text for item in session.history()] == ["look up"]
    assert services.cancelled == 1


def test_session_reuses_current_result_for_same_text() -> None:
    translator = _FakeTranslator(final=_result("время", "Time flies."))
    session, events, _ = _build_session(translator)
    session.translate("time")
    events.clear()

    snapshot = session.translate("time")

    assert translator.calls == ["time"]
    assert _phases(events) == [Phase.FINAL]
    assert snapshot.state.translation == "время"


def test_session_rejects_text_without_english() -> None:
    session, _, _ = _build_session(_FakeTranslator(final=_result("x")))

    with pytest.raises(SessionError) as excinfo:
        session.translate("1234 ---")

    assert excinfo.value.code is ErrorCode.INVALID_PARAMS


def test_session_history_select_and_copy_all() -> None:
    translator = _FakeTranslator(final=_result("банк", "The bank is closed."))
    session, events, _ = _build_session(translator)
    session.translate("bank")
    entry_id = session.history()[0].entry_id
    events.clear()

    snapshot = session.select_history(entry_id)
    text = session.copy_all_text()

    assert snapshot.entry_id == entry_id
    assert _phases(events) == [Phase.FINAL]
    assert text.splitlines()[0] == "Original: bank"
    assert "Translation: банк" in text
    assert "1. EN: The **bank** is closed." in text
    assert events[-1][0] is Event.NOTIFICATION


def test_session_refresh_examples_rotates_visible_examples() -> None:
    translator = _FakeTranslator(
        final=_result("время", "Time one.", "Time two.", "Time three."),
        refresh_pool=(
            Example("Time one."),
            Example("Time four."),
            Example("Time five."),
        ),
    )
    session, events, _ = _build_session(translator)
    session.translate("time")
    events.clear()
    replies: list[tuple[int, bool]] = []

    current_id = session.snapshot().request_id
    session.refresh_examples(
        lambda snap, changed: replies.append((snap.request_id, changed))
    )

    assert replies == [(current_id, True)]
    assert _phases(events) == [Phase.EXAMPLES, Phase.EXAMPLES]
    final_state = protocol.as_json_object(events[-1][1]["state"])
    assert final_state is not None
    assert final_state["examples"] == [{"en": "Time four."}, {"en": "Time five."}]
    assert final_state["refreshing_examples"] is False


def test_session_refresh_without_active_entry_fails() -> None:
    session, _, _ = _build_session(_FakeTranslator(final=_result("x")))

    with pytest.raises(SessionError) as excinfo:
        session.refresh_examples(lambda snap, changed: None)

    assert excinfo.value.code is ErrorCode.NO_ACTIVE_ENTRY


# --- api -------------------------------------------------------------------------------


def test_backend_api_dispatches_translate_and_rejects_unknown_method(
    tmp_path: Path,
) -> None:
    translator = _FakeTranslator(final=_result("время", "Time flies."))
    session, _, _ = _build_session(translator)

    async def scenario() -> None:
        api = BackendApi(
            session=session,
            loop=asyncio.get_running_loop(),
            socket_path=tmp_path / "s.sock",
            request_shutdown=lambda: None,
            engines=lambda: {"apple_dictionary": True, "apple_translation": False},
        )
        ping = await api.handle(Request(id=1, method="ping", params={}))
        assert ping["protocol"] == protocol.PROTOCOL_VERSION
        assert ping["engines"] == {"apple_dictionary": True, "apple_translation": False}

        result = await api.handle(
            Request(id=2, method="translate", params={"text": "time"})
        )
        assert result["request_id"] == session.snapshot().request_id
        state = protocol.as_json_object(result["state"])
        assert state is not None and state["translation"] == "время"

        history = await api.handle(Request(id=3, method="history.list", params={}))
        items = history["items"]
        assert isinstance(items, list) and len(items) == 1

        with pytest.raises(ProtocolDecodeError) as excinfo:
            await api.handle(Request(id=4, method="nope", params={}))
        assert excinfo.value.code is ErrorCode.UNKNOWN_METHOD

        with pytest.raises(ProtocolDecodeError) as bad_params:
            await api.handle(Request(id=5, method="translate", params={}))
        assert bad_params.value.code is ErrorCode.INVALID_PARAMS

    asyncio.run(scenario())


def test_settings_flow_reports_anki_reachability() -> None:
    """`anki.status` must not claim Anki is up when the model query failed."""
    from desktop_app.application.use_cases.settings_flow import SettingsFlow
    from desktop_app.infrastructure.anki import AnkiListResult

    class _Service:
        def __init__(self, result: AnkiListResult) -> None:
            self._result = result

        def model_names(self) -> Future[AnkiListResult]:
            future: Future[AnkiListResult] = Future()
            future.set_result(self._result)
            return future

    class _Runtime:
        @property
        def loop(self) -> object:
            return object()

    reachability: list[bool] = []

    def build(result: AnkiListResult) -> SettingsFlow:
        return SettingsFlow(
            config=_config(),
            runtime=cast(AsyncRuntime, _Runtime()),
            anki_flow=AnkiFlow(service=cast("object", _Service(result))),  # type: ignore[arg-type]
            on_save=lambda config: None,
            dispatch=call_inline,
            on_reachability=reachability.append,
        )

    build(AnkiListResult(items=[], error="Cannot connect to host 127.0.0.1:8765"))
    assert reachability == [False]

    reachability.clear()
    build(AnkiListResult(items=["Translator"], error=None))
    assert reachability == [True]
