from __future__ import annotations

import asyncio
from contextlib import suppress
import threading


class AsyncRuntime:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait()

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        with suppress(Exception):
            loop.call_soon_threadsafe(loop.stop)
        thread = self._thread
        if thread is None:
            self._loop = None
            return
        if not thread.is_alive():
            self._thread = None
            self._loop = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("Async runtime is not started.")
        return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        self._loop = None
        self._thread = None
