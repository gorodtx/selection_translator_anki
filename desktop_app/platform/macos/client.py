"""Tiny CLI client for smoke-testing the macOS backend over its socket.

Examples::

    python -m desktop_app.platform.macos.client ping
    python -m desktop_app.platform.macos.client translate '{"text": "look up"}'
    python -m desktop_app.platform.macos.client history.list
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

from desktop_app.platform import paths
from desktop_app.platform.macos.ipc.protocol import (
    MAX_LINE_BYTES,
    Event,
    JsonObject,
    Method,
    Phase,
    as_json_object,
    encode_line,
)


async def call(
    *,
    socket_path: Path,
    method: str,
    params: JsonObject,
    wait_final: bool,
    timeout: float,
) -> int:
    reader, writer = await asyncio.open_unix_connection(
        path=str(socket_path), limit=MAX_LINE_BYTES
    )
    request_id = "cli-1"
    writer.write(encode_line({"id": request_id, "method": method, "params": params}))
    await writer.drain()
    deadline = time.monotonic() + timeout
    got_response = False
    exit_code = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print("timeout waiting for backend", file=sys.stderr)
                return 2
            try:
                line = await asyncio.wait_for(reader.readline(), remaining)
            except TimeoutError:
                print("timeout waiting for backend", file=sys.stderr)
                return 2
            if not line:
                print("backend closed connection", file=sys.stderr)
                return 3
            message = as_json_object(json.loads(line.decode("utf-8")))
            if message is None:
                continue
            print(json.dumps(message, ensure_ascii=False, indent=2))
            if message.get("id") == request_id:
                got_response = True
                if message.get("ok") is False:
                    exit_code = 1
                if not wait_final:
                    return exit_code
            if message.get("event") == str(Event.TRANSLATION_STATE):
                payload = as_json_object(message.get("payload")) or {}
                if payload.get("phase") in {str(Phase.FINAL), str(Phase.ERROR)}:
                    if got_response:
                        return exit_code
    finally:
        writer.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translator macOS backend client")
    parser.add_argument("method", help="protocol method, e.g. ping / translate")
    parser.add_argument("params", nargs="?", default="{}", help="JSON params object")
    parser.add_argument("--socket", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="for translate: return after the response instead of the final event",
    )
    args = parser.parse_args(argv)
    params = as_json_object(json.loads(str(args.params)))
    if params is None:
        print("params must be a JSON object", file=sys.stderr)
        return 64
    socket_path: Path = args.socket if args.socket is not None else paths.socket_path()
    wait_final = args.method == str(Method.TRANSLATE) and not bool(args.no_wait)
    return asyncio.run(
        call(
            socket_path=socket_path,
            method=str(args.method),
            params=params,
            wait_final=wait_final,
            timeout=float(args.timeout),
        )
    )


if __name__ == "__main__":
    sys.exit(main())
