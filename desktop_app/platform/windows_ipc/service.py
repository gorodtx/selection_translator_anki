from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import sys
import threading
from typing import Protocol

from desktop_app.platform.windows_ipc.named_pipe import pipe_name
from desktop_app.platform.windows_ipc.protocol import (
    PipeCommand,
    PipeResponse,
    decode_command,
    encode_response,
)

LOGGER = logging.getLogger(__name__)


class PipeConnection(Protocol):
    def recv(self) -> bytes: ...

    def send(self, payload: bytes) -> None: ...

    def close(self) -> None: ...


class PipeServer(Protocol):
    def accept(self) -> PipeConnection: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PipeHandlers:
    on_translate: Callable[[str], None]
    on_show_settings: Callable[[], None]
    on_show_history: Callable[[], None]
    on_get_anki_status: Callable[[], dict[str, str]]


@dataclass(slots=True)
class WindowsIpcService:
    handlers: PipeHandlers
    server: PipeServer
    _thread: threading.Thread | None = None
    _closed: bool = False

    @classmethod
    def register(
        cls,
        *,
        handlers: PipeHandlers,
        server_factory: Callable[[], PipeServer | None] | None = None,
    ) -> "WindowsIpcService | None":
        factory = server_factory or _default_server_factory
        try:
            server = factory()
        except Exception:
            LOGGER.exception("Failed to initialize Windows IPC server.")
            return None
        if server is None:
            return None
        service = cls(handlers=handlers, server=server)
        service._thread = threading.Thread(target=service._serve, daemon=True)
        service._thread.start()
        return service

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.server.close()
        except Exception:
            pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join()
        self._thread = None

    def _serve(self) -> None:
        while not self._closed:
            try:
                connection = self.server.accept()
            except Exception:
                if self._closed:
                    break
                LOGGER.exception("Failed to accept Windows IPC connection.")
                continue
            self._handle_connection(connection)

    def _handle_connection(self, connection: PipeConnection) -> None:
        try:
            raw = connection.recv()
            response = dispatch_command(raw, self.handlers)
            connection.send(response)
        except Exception:
            LOGGER.exception("Failed to process Windows IPC request.")
        finally:
            try:
                connection.close()
            except Exception:
                pass


def dispatch_command(raw: bytes, handlers: PipeHandlers) -> bytes:
    try:
        command = decode_command(raw)
        response = _dispatch_decoded(command, handlers)
        return encode_response(response)
    except Exception as exc:
        message = str(exc).strip() or "Invalid IPC request."
        return encode_response(PipeResponse(status="error", message=message))


def _dispatch_decoded(command: PipeCommand, handlers: PipeHandlers) -> PipeResponse:
    if command.name == "ping":
        return PipeResponse(status="ok", message="pong")
    if command.name == "translate":
        handlers.on_translate(command.text)
        return PipeResponse(status="ok", message="accepted")
    if command.name == "show_settings":
        handlers.on_show_settings()
        return PipeResponse(status="ok", message="accepted")
    if command.name == "show_history":
        handlers.on_show_history()
        return PipeResponse(status="ok", message="accepted")
    if command.name == "get_anki_status":
        payload = handlers.on_get_anki_status()
        return PipeResponse(status="ok", message="ok", payload=payload)
    raise ValueError("Unsupported command.")


def _default_server_factory() -> PipeServer | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        from multiprocessing.connection import Listener
    except Exception:
        return None
    listener = Listener(address=pipe_name(), family="AF_PIPE")
    return _MultiprocessingServer(listener)


@dataclass(slots=True)
class _MultiprocessingConnection(PipeConnection):
    connection: object

    def recv(self) -> bytes:
        recv_bytes = getattr(self.connection, "recv_bytes")
        value: bytes = recv_bytes()
        return value

    def send(self, payload: bytes) -> None:
        send_bytes = getattr(self.connection, "send_bytes")
        send_bytes(payload)

    def close(self) -> None:
        close = getattr(self.connection, "close")
        close()


@dataclass(slots=True)
class _MultiprocessingServer(PipeServer):
    listener: object

    def accept(self) -> PipeConnection:
        accept = getattr(self.listener, "accept")
        connection = accept()
        return _MultiprocessingConnection(connection=connection)

    def close(self) -> None:
        close = getattr(self.listener, "close")
        close()
