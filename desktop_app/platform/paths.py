from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Final

from translate_logic.infrastructure.language_base.locations import (
    default_offline_base_dir,
    user_data_dir,
)

CONFIG_DIR_ENV: Final[str] = "TRANSLATOR_CONFIG_DIR"
RUNTIME_DIR_ENV: Final[str] = "TRANSLATOR_RUNTIME_DIR"
SOCKET_PATH_ENV: Final[str] = "TRANSLATOR_SOCKET_PATH"
LOG_DIR_ENV: Final[str] = "TRANSLATOR_LOG_DIR"
_LINUX_DIR_NAME: Final[str] = "translator"
_MAC_DIR_NAME: Final[str] = "Translator"
_SOCKET_FILE_NAME: Final[str] = "backend.sock"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def config_dir() -> Path:
    override = _env_path(CONFIG_DIR_ENV)
    if override is not None:
        return override
    if is_macos():
        return Path.home() / "Library" / "Application Support" / _MAC_DIR_NAME
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_home) if xdg_home else Path.home() / ".config"
    return base / _LINUX_DIR_NAME


def data_dir() -> Path:
    return user_data_dir()


def db_dir() -> Path:
    return default_offline_base_dir()


def runtime_dir() -> Path:
    override = _env_path(RUNTIME_DIR_ENV)
    if override is not None:
        return override
    if is_macos():
        return data_dir() / "run"
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        return Path(xdg_runtime) / _LINUX_DIR_NAME
    return config_dir()


def socket_path() -> Path:
    override = _env_path(SOCKET_PATH_ENV)
    if override is not None:
        return override
    return runtime_dir() / _SOCKET_FILE_NAME


def log_dir() -> Path:
    override = _env_path(LOG_DIR_ENV)
    if override is not None:
        return override
    if is_macos():
        return Path.home() / "Library" / "Logs" / _MAC_DIR_NAME
    return data_dir() / "logs"


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()
