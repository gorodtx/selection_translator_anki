"""Headless macOS backend: shared services + session behind the UDS protocol.

Run with ``python -m desktop_app.platform.macos.daemon``. The SwiftUI shell
connects to :func:`desktop_app.platform.paths.socket_path`.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
import concurrent.futures
import contextlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys
from typing import Final

from desktop_app.application.anki_status import AnkiActionResult
from desktop_app.application.use_cases.anki_upsert import AnkiUpsertPreview
from desktop_app.config import AppConfig, load_config, save_config
from desktop_app.infrastructure.services.container import AppServices
from desktop_app.platform import paths
from desktop_app.platform.macos.ipc.protocol import (
    PROTOCOL_VERSION,
    ErrorCode,
    Event,
    JsonObject,
    Method,
    ProtocolDecodeError,
    Request,
    action_result_to_json,
    anki_decision_from_json,
    anki_preview_to_json,
    anki_status_to_json,
    config_from_json,
    config_to_json,
    deck_list_to_json,
    get_int,
    get_object,
    get_str,
    history_item_to_json,
    view_state_to_json,
)
from desktop_app.platform.macos.ipc.server import IpcServer
from desktop_app.platform.macos.session import (
    BackendSession,
    SessionError,
    StateSnapshot,
    UpsertOutcome,
)
from translate_logic.infrastructure.language_base.locations import (
    resolve_offline_base_file,
)
from translate_logic.infrastructure.providers import apple

BACKEND_VERSION: Final[str] = "0.3.0"
_ANKI_TIMEOUT_S: Final[float] = 20.0
_EXAMPLES_TIMEOUT_S: Final[float] = 15.0
_SETTINGS_TIMEOUT_S: Final[float] = 5.0
_DB_FILES: Final[dict[str, str]] = {
    "primary": "primary.sqlite3",
    "fallback": "fallback.sqlite3",
    "definitions": "definitions_pack.sqlite3",
}

logger = logging.getLogger(__name__)


def engine_status() -> JsonObject:
    return apple.engine_status()


def db_status() -> JsonObject:
    """Report which offline bases are reachable and where they live.

    ``dir`` is the directory the primary base actually resolved from, which is
    not always the download directory: an explicit override or a repo checkout
    can supply the files from elsewhere.
    """
    status: JsonObject = {}
    resolved_dir = paths.db_dir()
    for key, name in _DB_FILES.items():
        path = resolve_offline_base_file(name)
        exists = path.exists()
        status[key] = exists
        if exists and key == "primary":
            resolved_dir = path.parent
    status["dir"] = str(resolved_dir)
    return status


class BackendApi:
    def __init__(
        self,
        *,
        session: BackendSession,
        loop: asyncio.AbstractEventLoop,
        socket_path: Path,
        request_shutdown: Callable[[], None],
        engines: Callable[[], JsonObject] = engine_status,
        refresh_engines: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._loop = loop
        self._socket_path = socket_path
        self._request_shutdown = request_shutdown
        self._engines = engines
        self._refresh_engines = refresh_engines

    async def handle(self, request: Request) -> JsonObject:
        try:
            method = Method(request.method)
        except ValueError as exc:
            raise ProtocolDecodeError(
                ErrorCode.UNKNOWN_METHOD, f"Unknown method {request.method!r}."
            ) from exc
        try:
            return await self._dispatch(method, request.params)
        except SessionError as exc:
            raise ProtocolDecodeError(exc.code, exc.message) from exc
        except TimeoutError as exc:
            raise ProtocolDecodeError(
                ErrorCode.INTERNAL, f"{method} timed out."
            ) from exc

    async def _dispatch(self, method: Method, params: JsonObject) -> JsonObject:
        session = self._session
        if method is Method.PING:
            return self._ping()
        if method is Method.TRANSLATE:
            return _snapshot_json(session.translate(get_str(params, "text")))
        if method is Method.CANCEL or method is Method.CLOSE:
            session.cancel()
            return {}
        if method is Method.HISTORY_LIST:
            return {"items": [history_item_to_json(item) for item in session.history()]}
        if method is Method.HISTORY_SELECT:
            return _snapshot_json(session.select_history(get_int(params, "entry_id")))
        if method is Method.EXAMPLES_REFRESH:

            def start_refresh(
                reply: Callable[[tuple[StateSnapshot, bool]], None],
            ) -> None:
                session.refresh_examples(lambda snap, flag: reply((snap, flag)))

            snapshot, changed = await self._await_reply(
                start_refresh, _EXAMPLES_TIMEOUT_S
            )
            payload = _snapshot_json(snapshot)
            payload["changed"] = changed
            return payload
        if method is Method.COPY_ALL:
            return {"text": session.copy_all_text()}
        if method is Method.ANKI_STATUS:
            status = await self._await_reply(session.anki_status, _ANKI_TIMEOUT_S)
            return anki_status_to_json(status, available=session.anki_available)
        if method is Method.ANKI_DECKS:
            decks = await self._await_reply(session.anki_decks, _ANKI_TIMEOUT_S)
            return deck_list_to_json(decks)
        if method is Method.ANKI_SELECT_DECK:
            deck = get_str(params, "deck")

            def start_select(reply: Callable[[AnkiActionResult], None]) -> None:
                session.anki_select_deck(deck, reply)

            result = await self._await_reply(start_select, _ANKI_TIMEOUT_S)
            return action_result_to_json(result)
        if method is Method.ANKI_CREATE_MODEL:
            result = await self._await_reply(session.anki_create_model, _ANKI_TIMEOUT_S)
            return action_result_to_json(result)
        if method is Method.ANKI_PREPARE_UPSERT:

            def start_prepare(
                reply: Callable[[tuple[AnkiUpsertPreview | None, str | None]], None],
            ) -> None:
                session.anki_prepare_upsert(lambda prev, err: reply((prev, err)))

            preview, error = await self._await_reply(start_prepare, _ANKI_TIMEOUT_S)
            if preview is None:
                raise ProtocolDecodeError(
                    ErrorCode.ANKI, error or "Failed to prepare upsert."
                )
            return {"preview": anki_preview_to_json(preview)}
        if method is Method.ANKI_APPLY_UPSERT:
            decision = anki_decision_from_json(get_object(params, "decision"))

            def start_apply(reply: Callable[[UpsertOutcome], None]) -> None:
                session.anki_apply_upsert(decision, reply)

            outcome = await self._await_reply(start_apply, _ANKI_TIMEOUT_S)
            return {"outcome": outcome.outcome, "message": outcome.message}
        if method is Method.SETTINGS_GET:
            return config_to_json(session.config)
        if method is Method.SETTINGS_SAVE:
            config = config_from_json(get_object(params, "config"))

            def start_save(reply: Callable[[AnkiActionResult], None]) -> None:
                session.save_settings(config, reply)

            result = await self._await_reply(start_save, _SETTINGS_TIMEOUT_S)
            return action_result_to_json(result)
        if method is Method.SHUTDOWN:
            self._loop.call_soon(self._request_shutdown)
            return {}
        raise ProtocolDecodeError(ErrorCode.UNKNOWN_METHOD, f"Unhandled {method}.")

    def _ping(self) -> JsonObject:
        engines = self._engines()
        if engines.get("stale") is True and self._refresh_engines is not None:
            self._refresh_engines()
        return {
            "version": BACKEND_VERSION,
            "protocol": PROTOCOL_VERSION,
            "pid": os.getpid(),
            "platform": sys.platform,
            "socket": str(self._socket_path),
            "db": db_status(),
            "engines": engines,
        }

    async def _await_reply[T](
        self,
        start: Callable[[Callable[[T], None]], None],
        timeout: float,
    ) -> T:
        future: asyncio.Future[T] = self._loop.create_future()

        def _reply(value: T) -> None:
            if not future.done():
                future.set_result(value)

        start(_reply)
        return await asyncio.wait_for(future, timeout)


def _snapshot_json(snapshot: StateSnapshot) -> JsonObject:
    return {
        "request_id": snapshot.request_id,
        "state": view_state_to_json(
            snapshot.state,
            entry_id=snapshot.entry_id,
            lexical=snapshot.lexical,
            translation_raw=snapshot.translation_raw,
        ),
    }


class Daemon:
    def __init__(self, *, socket_path: Path) -> None:
        self._socket_path = socket_path
        self._stop_event: asyncio.Event | None = None

    def request_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        services = AppServices.create()
        services.start()
        config: AppConfig = load_config()

        def dispatch(callback: Callable[[], None]) -> None:
            loop.call_soon_threadsafe(callback)

        server: IpcServer | None = None

        def emit(event: Event, payload: JsonObject) -> None:
            if server is not None:
                server.broadcast(event, payload)

        session = BackendSession(
            services=services,
            config=config,
            dispatch=dispatch,
            emit=emit,
            save_config=save_config,
        )

        def refresh_engines() -> None:
            future = asyncio.run_coroutine_threadsafe(
                apple.refresh_status(), services.runtime.loop
            )
            future.add_done_callback(_log_engine_refresh)

        api = BackendApi(
            session=session,
            loop=loop,
            socket_path=self._socket_path,
            request_shutdown=self.request_stop,
            refresh_engines=refresh_engines,
        )
        if apple.is_available():
            refresh_engines()
        server = IpcServer(socket_path=self._socket_path, handler=api.handle)
        for signum in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(signum, self.request_stop)
        pid_path = _write_pid_file(self._socket_path)
        try:
            await server.start()
            logger.info("backend %s ready (pid %d)", BACKEND_VERSION, os.getpid())
            await self._stop_event.wait()
        finally:
            logger.info("backend shutting down")
            await server.stop()
            session.cancel()
            await _close_services(services)
            with contextlib.suppress(OSError):
                if pid_path is not None and pid_path.exists():
                    pid_path.unlink()


def _log_engine_refresh(
    future: concurrent.futures.Future[apple.AppleEngineStatus | None],
) -> None:
    try:
        status = future.result()
    except concurrent.futures.CancelledError:
        # Shutdown raced the probe; nothing to report.
        return
    except Exception:
        logger.exception("apple engine status refresh failed")
        return
    if status is None:
        logger.info("apple engines unavailable")
        return
    logger.info(
        "apple engines: dictionaries=%s translation=%s",
        list(status.dictionaries),
        status.translation_status,
    )


async def _close_services(services: AppServices) -> None:
    # AppServices.stop() cancels the close futures if they are not done yet;
    # give aiohttp sessions a moment to close cleanly before tearing down.
    for coroutine in (services.translator.close(), services.anki.close()):
        future = asyncio.run_coroutine_threadsafe(coroutine, services.runtime.loop)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.wrap_future(future), 2.0)
    services.stop()


def _write_pid_file(socket_path: Path) -> Path | None:
    pid_path = socket_path.with_name("backend.pid")
    try:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        return None
    return pid_path


def _configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    try:
        log_dir = paths.log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "backend.log", maxBytes=2_000_000, backupCount=3
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        logger.warning("file logging disabled: cannot create log dir")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translator macOS backend daemon")
    parser.add_argument(
        "--socket", type=Path, default=None, help="socket path override"
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    _configure_logging(str(args.log_level))
    socket_path: Path = args.socket if args.socket is not None else paths.socket_path()
    daemon = Daemon(socket_path=socket_path)
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
