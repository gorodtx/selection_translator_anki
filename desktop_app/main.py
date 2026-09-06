from __future__ import annotations

import io
import os
from pathlib import Path
import sys

from desktop_app.app import TranslatorApp
from desktop_app.config import config_path
from desktop_app.platform.paths import config_dir, is_windows

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
        base = config_dir()
        pid_path = base / "app.pid"
        if pid_path.exists():
            pid_path.unlink()
        lock_path = base / "app.lock"
        if lock_path.exists():
            lock_path.unlink()
    except OSError:
        pass


def _lock_path() -> Path:
    return config_dir() / "app.lock"


def _acquire_single_instance_lock() -> bool:
    if is_windows():
        return True
    try:
        import fcntl
    except ImportError:
        return True
    lock_path = _lock_path()
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return True
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(fd, "r+", encoding="utf-8")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    global _lock_handle
    _lock_handle = handle
    return True


def main() -> None:
    _reset_if_requested()
    if not _acquire_single_instance_lock():
        return
    app = TranslatorApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
