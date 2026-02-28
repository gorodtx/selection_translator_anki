from __future__ import annotations

import os
import re

from desktop_app.runtime_namespace import runtime_namespace

TRANSLATOR_WINDOWS_PIPE_NAME_ENV = "TRANSLATOR_WINDOWS_PIPE_NAME"
_PIPE_PREFIX = "\\\\.\\pipe\\"
_SAFE_TOKEN = re.compile(r"[^a-z0-9._-]+")


def pipe_name() -> str:
    value = os.environ.get(TRANSLATOR_WINDOWS_PIPE_NAME_ENV, "").strip()
    if value:
        return value
    token = _normalized_token(runtime_namespace())
    return f"{_PIPE_PREFIX}translator-{token}"


def _normalized_token(value: str) -> str:
    normalized = _SAFE_TOKEN.sub("-", value.strip().lower()).strip("-")
    if not normalized:
        return "default"
    return normalized
