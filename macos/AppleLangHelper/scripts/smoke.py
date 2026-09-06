#!/usr/bin/env python3
"""Drive the helper one request at a time with per-request timeouts (stdlib only)."""

from __future__ import annotations

import json
import selectors
import subprocess
import sys
import time

BIN = sys.argv[1] if len(sys.argv) > 1 else ".build/release/apple-lang-helper"
REQUESTS = [
    {"id": 1, "op": "ping"},
    {"id": 2, "op": "dictionaries"},
    {"id": 3, "op": "availability", "source": "en", "target": "ru"},
    {
        "id": 4,
        "op": "define",
        "term": "bank",
        "dictionary": "Oxford Russian",
        "include_markup": False,
    },
    {
        "id": 5,
        "op": "define",
        "term": "look up",
        "dictionary": "Oxford Russian",
        "max_records": 1,
    },
    {
        "id": 6,
        "op": "translate",
        "text": "How are you doing today?",
        "source": "en",
        "target": "ru",
    },
    {"id": 7, "op": "text_definition", "term": "nevertheless"},
    "garbage line",
    {"id": 8, "op": "shutdown"},
]


def main() -> int:
    proc = subprocess.Popen(
        [BIN],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin and proc.stdout
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    failures = 0
    for req in REQUESTS:
        line = req if isinstance(req, str) else json.dumps(req)
        started = time.perf_counter()
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
        if sel.select(timeout=5.0):
            out = proc.stdout.readline().rstrip("\n")
            elapsed = (time.perf_counter() - started) * 1000
            preview = out if len(out) <= 300 else out[:300] + f"... ({len(out)} chars)"
            print(f"[{elapsed:7.1f} ms] {preview}")
        else:
            failures += 1
            print(f"[TIMEOUT 5s] no response to: {line}")
            break
    try:
        proc.wait(timeout=3)
        print(f"exit code: {proc.returncode}")
    except subprocess.TimeoutExpired:
        failures += 1
        proc.kill()
        print("process did not exit after shutdown; killed")
    err = proc.stderr.read() if proc.stderr else ""
    if err:
        print("stderr:", err[:500])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
