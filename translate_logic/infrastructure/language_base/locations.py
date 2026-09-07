from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Final

DB_DIR_ENV: Final[str] = "TRANSLATOR_DB_DIR"
_MAC_APP_SUPPORT_DIR_NAME: Final[str] = "Translator"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def is_macos() -> bool:
    return sys.platform == "darwin"


def user_data_dir() -> Path:
    """Per-user data root used for the shared offline base store."""
    if is_macos():
        return (
            Path.home() / "Library" / "Application Support" / _MAC_APP_SUPPORT_DIR_NAME
        )
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "translator"


def default_offline_base_dir() -> Path:
    override = os.environ.get(DB_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    if is_macos():
        return user_data_dir() / "db"
    return repo_offline_base_candidates()[0]


def offline_base_dir_candidates() -> tuple[Path, ...]:
    """Where to look for an offline base, in order.

    An explicit ``TRANSLATOR_DB_DIR`` is the only candidate. Every other
    override in this project is a directive — config dir, runtime dir, socket
    path, log dir all return immediately — and this one behaving as a hint
    made the two halves of the system disagree: the installer decides what to
    download from the override, while the runtime would happily read the bases
    from somewhere else and report success for a directory that is empty.

    With no override the chain still falls through per file, which is what
    makes a repo checkout work alongside the shared store.
    """
    override = os.environ.get(DB_DIR_ENV, "").strip()
    if override:
        return (Path(override).expanduser(),)
    candidates: list[Path] = []
    if is_macos():
        candidates.append(user_data_dir() / "db")
    candidates.extend(repo_offline_base_candidates())
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return tuple(unique)


def resolve_offline_base_file(filename: str) -> Path:
    for base_dir in offline_base_dir_candidates():
        candidate = base_dir / filename
        if candidate.exists():
            return candidate
    return default_offline_base_dir() / filename


def repo_offline_base_candidates() -> tuple[Path, ...]:
    repo_root = _repo_root()
    return (
        repo_root
        / "translate_logic"
        / "infrastructure"
        / "language_base"
        / "offline_language_base",
        repo_root / "translate_logic" / "language_base" / "offline_language_base",
        repo_root / "offline_language_base",
    )
