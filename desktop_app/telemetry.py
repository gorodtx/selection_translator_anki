from __future__ import annotations

import atexit
from datetime import datetime, timezone
import hashlib
import json
import logging
import logging.handlers
import os
from pathlib import Path
import queue
import threading
from typing import Final

_LOGGER_NAME: Final[str] = "translator"
_LOG_DIR_ENV: Final[str] = "TRANSLATOR_LOG_DIR"
_LOG_ENABLED_ENV: Final[str] = "TRANSLATOR_LOGGING"
_logger: logging.Logger | None = None
_listener: logging.handlers.QueueListener | None = None
_file_handler: logging.Handler | None = None


def log_path() -> Path:
    override = os.environ.get(_LOG_DIR_ENV, "").strip()
    if override:
        return Path(override) / "translator.log"
    return Path.home() / ".translator" / "logs" / "translator.log"


def setup(*, reset: bool) -> None:
    global _logger, _listener, _file_handler
    if not _is_enabled():
        return
    if _logger is not None:
        return
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    mode = "w" if reset else "a"
    file_handler = logging.FileHandler(path, mode=mode, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    file_handler.setLevel(logging.INFO)
    record_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    queue_handler = logging.handlers.QueueHandler(record_queue)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(queue_handler)
    listener = logging.handlers.QueueListener(
        record_queue,
        file_handler,
        respect_handler_level=True,
    )
    listener.start()
    _logger = logger
    _listener = listener
    _file_handler = file_handler
    atexit.register(shutdown)


def shutdown() -> None:
    global _logger, _listener, _file_handler
    if _listener is not None:
        _listener.stop()
        _listener = None
    if _file_handler is not None:
        _file_handler.close()
        _file_handler = None
    if _logger is not None:
        _logger.handlers.clear()
        _logger = None


def log_event(event: str, **fields: object) -> None:
    _ensure_setup()
    logger = _logger
    if logger is None or not logger.isEnabledFor(logging.INFO):
        return
    payload = _base_payload(event)
    if fields:
        payload.update(_sanitize_fields(fields))
    logger.info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def log_error(event: str, exc: BaseException | None = None, **fields: object) -> None:
    _ensure_setup()
    logger = _logger
    if logger is None or not logger.isEnabledFor(logging.ERROR):
        return
    payload = _base_payload(event)
    if exc is not None:
        payload["error_type"] = exc.__class__.__name__
        payload["error"] = str(exc)
    if fields:
        payload.update(_sanitize_fields(fields))
    logger.error(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def text_meta(value: str | None) -> dict[str, object]:
    if not value:
        return {"text_len": 0, "text_hash": ""}
    data = value.encode("utf-8", errors="ignore")
    digest = hashlib.sha256(data).hexdigest()
    return {"text_len": len(value), "text_hash": digest}


def _ensure_setup() -> None:
    if _logger is None:
        setup(reset=False)


def _is_enabled() -> bool:
    return os.environ.get(_LOG_ENABLED_ENV, "1").strip() != "0"


def _base_payload(event: str) -> dict[str, object]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        "pid": os.getpid(),
        "thread": threading.get_ident(),
    }


def _sanitize_fields(fields: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in fields.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[key] = value
        else:
            sanitized[key] = str(value)
    return sanitized
