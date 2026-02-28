from __future__ import annotations

import io
import os
from pathlib import Path
import sys

from desktop_app.config import config_path
from desktop_app.platform.paths import runtime_state_home
from desktop_app.runtime_namespace import runtime_namespace

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
        ns = runtime_namespace()
        state_dir = runtime_state_home(ns)
        pid_path = state_dir / "app.pid"
        if pid_path.exists():
            pid_path.unlink()
        lock_path = state_dir / "app.lock"
        if lock_path.exists():
            lock_path.unlink()
    except OSError:
        pass


def _lock_path() -> Path:
    return runtime_state_home(runtime_namespace()) / "app.lock"


def _acquire_single_instance_lock() -> bool:
    lock_path = _lock_path()
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return True
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(fd, "r+", encoding="utf-8")
    if sys.platform.startswith("linux"):
        try:
            import fcntl
        except ImportError:
            handle.close()
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
    elif sys.platform.startswith("win"):
        try:
            import msvcrt
        except ImportError:
            handle.close()
            return True
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
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
    from desktop_app.app import TranslatorApp

    _reset_if_requested()
    if not _acquire_single_instance_lock():
        return
    app = TranslatorApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
