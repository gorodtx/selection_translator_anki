from __future__ import annotations

import pytest

from desktop_app.platform.windows_ipc import named_pipe, protocol


def test_pipe_name_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv(named_pipe.TRANSLATOR_WINDOWS_PIPE_NAME_ENV, r"\\.\pipe\translator-custom")
    monkeypatch.setenv("TRANSLATOR_RUNTIME_NAMESPACE", "translator-dev")

    resolved = named_pipe.pipe_name()

    assert resolved == r"\\.\pipe\translator-custom"


def test_pipe_name_falls_back_to_runtime_namespace(monkeypatch) -> None:
    monkeypatch.delenv(named_pipe.TRANSLATOR_WINDOWS_PIPE_NAME_ENV, raising=False)
    monkeypatch.setenv("TRANSLATOR_RUNTIME_NAMESPACE", "Translator Dev !!")

    resolved = named_pipe.pipe_name()

    assert resolved == r"\\.\pipe\translator-translator-dev"


def test_protocol_roundtrip_translate() -> None:
    command = protocol.PipeCommand(name="translate", text="hello world")
    encoded = protocol.encode_command(command)

    decoded = protocol.decode_command(encoded)

    assert decoded == command


def test_protocol_roundtrip_response_with_payload() -> None:
    response = protocol.PipeResponse(
        status="ok",
        message="ready",
        payload={"deck_status": "selected"},
    )
    encoded = protocol.encode_response(response)

    decoded = protocol.decode_response(encoded)

    assert decoded == response


def test_decode_command_rejects_invalid_payload() -> None:
    with pytest.raises(ValueError):
        protocol.decode_command(b"{\"name\":\"translate\",\"text\":1}")
