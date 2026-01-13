from __future__ import annotations

import io
import os
from pathlib import Path
import sys

from desktop_app.app import TranslatorApp
from desktop_app.config import config_path
from desktop_app.services.selection_cache import selection_cache_path
from desktop_app import telemetry

_lock_handle: io.TextIOWrapper | None = None


def _reset_if_requested() -> None:
    if os.environ.get("TRANSLATOR_RESET", "").strip() != "1":
        return
    os.environ.pop("TRANSLATOR_RESET", None)
    try:
        path = config_path()
        if path.exists():
            path.unlink()
    except OSError:
        pass
    try:
        sel_path = selection_cache_path()
        if sel_path.exists():
            sel_path.unlink()
    except OSError:
        pass
    try:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        pid_path = base / "translator" / "app.pid"
        if pid_path.exists():
            pid_path.unlink()
        lock_path = base / "translator" / "app.lock"
        if lock_path.exists():
            lock_path.unlink()
    except OSError:
        pass


def _lock_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "translator" / "app.lock"


def _acquire_single_instance_lock() -> bool:
    if not sys.platform.startswith("linux"):
        telemetry.log_event("single_instance.skip", reason="not_linux")
        return True
    try:
        import fcntl
    except ImportError:
        telemetry.log_event("single_instance.skip", reason="no_fcntl")
        return True
    lock_path = _lock_path()
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        telemetry.log_error("single_instance.lock_dir_failed")
        return True
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(fd, "r+", encoding="utf-8")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        telemetry.log_event("single_instance.lock_busy")
        return False
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    global _lock_handle
    _lock_handle = handle
    telemetry.log_event("single_instance.lock_acquired")
    return True


def main() -> None:
    reset_flag = os.environ.pop("TRANSLATOR_LOG_RESET", "").strip()
    reset_logs = reset_flag != "0"
    telemetry.setup(reset=reset_logs)
    telemetry.log_event("main.start")
    _reset_if_requested()
    if not _acquire_single_instance_lock():
        telemetry.log_event("main.exit", reason="lock_busy")
        return
    app = TranslatorApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
