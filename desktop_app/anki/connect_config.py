from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeGuard

DEFAULT_CONFIG_PATH = Path.home() / ".local/share/Anki2/addons21/2055492159/config.json"
FLATPAK_CONFIG_PATH = (
    Path.home() / ".var/app/net.ankiweb.Anki/data/Anki2/addons21/2055492159/config.json"
)


def detect_anki_connect_url() -> str | None:
    env_url = os.environ.get("ANKI_CONNECT_URL")
    if env_url:
        return env_url
    config_path = _resolve_config_path()
    data = _read_config(config_path) if config_path is not None else None
    if data is None:
        return None
    address = _coerce_str(data.get("webBindAddress"))
    port = _coerce_int(data.get("webBindPort"))
    if port is None:
        return None
    host = address or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _resolve_config_path() -> Path | None:
    for path in _candidate_config_paths():
        if path.exists():
            return path
    return None


def _candidate_config_paths() -> list[Path]:
    candidates = [DEFAULT_CONFIG_PATH, FLATPAK_CONFIG_PATH]
    base_dirs = [DEFAULT_CONFIG_PATH.parent.parent, FLATPAK_CONFIG_PATH.parent.parent]
    for base_dir in base_dirs:
        if not base_dir.exists():
            continue
        try:
            for path in base_dir.glob("*/addons21/2055492159/config.json"):
                candidates.append(path)
        except OSError:
            continue
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _read_config(path: Path) -> dict[str, object] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        payload: object = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if _is_str_dict(payload):
        return dict(payload)
    return None


def _coerce_str(value: object | None) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _coerce_int(value: object | None) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _is_str_dict(value: object | None) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)
