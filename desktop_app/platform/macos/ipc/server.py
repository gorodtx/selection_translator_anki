from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging
import os
from pathlib import Path
import socket

from desktop_app.platform.macos.ipc.protocol import (
    MAX_LINE_BYTES,
    ErrorCode,
    Event,
    JsonObject,
    ProtocolDecodeError,
    ProtocolError,
    Request,
    decode_request,
    encode_error,
    encode_event,
    encode_response,
)

logger = logging.getLogger(__name__)

type RequestHandler = Callable[[Request], Awaitable[JsonObject]]

# sun_path is 104 bytes on Darwin (108 on Linux) including the terminator.
MAX_SOCKET_PATH_BYTES = 103
# Closed clients let `wait_closed()` return at once; the bound only exists so
# one wedged handler cannot hang the shutdown.
_SHUTDOWN_TIMEOUT_S = 2.0


class IpcServer:
    """NDJSON request/response + broadcast server over a Unix domain socket."""

    def __init__(self, *, socket_path: Path, handler: RequestHandler) -> None:
        self._socket_path = socket_path
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._owns_socket = False

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def client_count(self) -> int:
        return len(self._writers)

    async def start(self) -> None:
        encoded_length = len(str(self._socket_path).encode("utf-8"))
        if encoded_length > MAX_SOCKET_PATH_BYTES:
            raise RuntimeError(
                f"socket path is {encoded_length} bytes; AF_UNIX allows at most "
                f"{MAX_SOCKET_PATH_BYTES} ({self._socket_path})"
            )
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        _remove_stale_socket(self._socket_path)
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._socket_path),
            limit=MAX_LINE_BYTES,
        )
        self._owns_socket = True
        os.chmod(self._socket_path, 0o600)
        logger.info("ipc listening on %s", self._socket_path)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Shut down without waiting on clients that will never speak again.

        `wait_closed()` waits for the connection handlers, and a handler sits
        in `readline()` for as long as its client holds the socket open. An
        idle client therefore pinned the daemon alive indefinitely: it logged
        that it was shutting down, unlinked the socket, and then waited. Since
        launchd restarts an agent with SIGTERM, the backend could never be
        replaced — only `kill -9` ended it. Close the clients first.
        """
        server = self._server
        self._server = None
        if server is not None:
            server.close()
        for writer in list(self._writers):
            self._drop_writer(writer)
        if server is not None:
            close_clients = getattr(server, "close_clients", None)
            if callable(close_clients):
                with contextlib.suppress(Exception):
                    close_clients()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(server.wait_closed(), _SHUTDOWN_TIMEOUT_S)
            abort_clients = getattr(server, "abort_clients", None)
            if callable(abort_clients):
                with contextlib.suppress(Exception):
                    abort_clients()
        if not self._owns_socket:
            # A failed start (for example: another backend already listening)
            # must never remove the socket that instance is serving.
            return
        self._owns_socket = False
        with contextlib.suppress(OSError):
            if self._socket_path.exists():
                self._socket_path.unlink()

    def broadcast(self, event: Event, payload: JsonObject) -> None:
        if not self._writers:
            return
        data = encode_event(event, payload)
        for writer in list(self._writers):
            try:
                writer.write(data)
            except Exception:
                self._drop_writer(writer)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        logger.debug("ipc client connected (%d total)", len(self._writers))
        try:
            while True:
                try:
                    line = await reader.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    writer.write(
                        encode_error(
                            None,
                            ProtocolError(
                                ErrorCode.BAD_REQUEST, "Request line too long."
                            ),
                        )
                    )
                    break
                if not line:
                    break
                if not line.strip():
                    continue
                await self._process_line(line, writer)
                try:
                    await writer.drain()
                except (ConnectionError, OSError):
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ipc client loop failed")
        finally:
            self._drop_writer(writer)
            logger.debug("ipc client disconnected (%d total)", len(self._writers))

    async def _process_line(self, line: bytes, writer: asyncio.StreamWriter) -> None:
        try:
            request = decode_request(line)
        except ProtocolDecodeError as exc:
            writer.write(encode_error(None, ProtocolError(exc.code, exc.message)))
            return
        try:
            result = await self._handler(request)
        except ProtocolDecodeError as exc:
            writer.write(encode_error(request.id, ProtocolError(exc.code, exc.message)))
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("ipc handler failed for %s", request.method)
            writer.write(
                encode_error(
                    request.id,
                    ProtocolError(ErrorCode.INTERNAL, str(exc) or "Internal error."),
                )
            )
            return
        writer.write(encode_response(request.id, result))

    def _drop_writer(self, writer: asyncio.StreamWriter) -> None:
        self._writers.discard(writer)
        with contextlib.suppress(Exception):
            writer.close()


def _remove_stale_socket(path: Path) -> None:
    if not path.exists():
        return
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.2)
        probe.connect(str(path))
    except OSError:
        with contextlib.suppress(OSError):
            path.unlink()
        return
    finally:
        probe.close()
    raise RuntimeError(f"another backend is already listening on {path}")
