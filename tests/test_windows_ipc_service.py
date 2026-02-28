from __future__ import annotations

from desktop_app.platform.windows_ipc import (
    PipeCommand,
    PipeHandlers,
    decode_response,
    dispatch_command,
    encode_command,
)


def _handlers(
    calls: list[str], status_payload: dict[str, str] | None = None
) -> PipeHandlers:
    payload = status_payload or {
        "model_status": "Model ready",
        "deck_status": "Selected",
        "deck_name": "main",
    }
    return PipeHandlers(
        on_translate=lambda text: calls.append(f"translate:{text}"),
        on_show_settings=lambda: calls.append("show_settings"),
        on_show_history=lambda: calls.append("show_history"),
        on_get_anki_status=lambda: payload,
    )


def test_dispatch_ping_returns_pong() -> None:
    raw = encode_command(PipeCommand(name="ping"))

    encoded_response = dispatch_command(raw, _handlers([]))
    response = decode_response(encoded_response)

    assert response.status == "ok"
    assert response.message == "pong"


def test_dispatch_translate_calls_handler() -> None:
    calls: list[str] = []
    raw = encode_command(PipeCommand(name="translate", text="hello"))

    encoded_response = dispatch_command(raw, _handlers(calls))
    response = decode_response(encoded_response)

    assert response.status == "ok"
    assert response.message == "accepted"
    assert calls == ["translate:hello"]


def test_dispatch_show_entries_call_handlers() -> None:
    calls: list[str] = []
    settings_raw = encode_command(PipeCommand(name="show_settings"))
    history_raw = encode_command(PipeCommand(name="show_history"))

    settings_resp = decode_response(dispatch_command(settings_raw, _handlers(calls)))
    history_resp = decode_response(dispatch_command(history_raw, _handlers(calls)))

    assert settings_resp.status == "ok"
    assert history_resp.status == "ok"
    assert calls == ["show_settings", "show_history"]


def test_dispatch_get_anki_status_returns_payload() -> None:
    payload = {
        "model_status": "Model not found",
        "deck_status": "Not selected",
        "deck_name": "",
    }
    raw = encode_command(PipeCommand(name="get_anki_status"))

    encoded_response = dispatch_command(raw, _handlers([], payload))
    response = decode_response(encoded_response)

    assert response.status == "ok"
    assert response.payload == payload


def test_dispatch_invalid_json_returns_error() -> None:
    encoded_response = dispatch_command(b"{bad json", _handlers([]))
    response = decode_response(encoded_response)

    assert response.status == "error"
