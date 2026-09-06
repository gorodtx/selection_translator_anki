from __future__ import annotations

from pathlib import Path

import pytest

from desktop_app.platform import paths
from translate_logic.infrastructure.language_base import locations


def _force_platform(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(locations.sys, "platform", platform)
    monkeypatch.setattr(paths.sys, "platform", platform)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "TRANSLATOR_DB_DIR",
        "TRANSLATOR_CONFIG_DIR",
        "TRANSLATOR_RUNTIME_DIR",
        "TRANSLATOR_SOCKET_PATH",
        "TRANSLATOR_LOG_DIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


def test_macos_defaults_live_in_application_support(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _force_platform(monkeypatch, "darwin")
    support = tmp_path / "Library" / "Application Support" / "Translator"

    assert paths.config_dir() == support
    assert paths.data_dir() == support
    assert paths.db_dir() == support / "db"
    assert paths.runtime_dir() == support / "run"
    assert paths.socket_path() == support / "run" / "backend.sock"
    assert paths.log_dir() == tmp_path / "Library" / "Logs" / "Translator"


def test_linux_defaults_keep_xdg_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _force_platform(monkeypatch, "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    assert paths.config_dir() == tmp_path / "cfg" / "translator"
    assert paths.data_dir() == tmp_path / "data" / "translator"
    assert paths.runtime_dir() == tmp_path / "run" / "translator"
    repo_default = locations.repo_offline_base_candidates()[0]
    assert paths.db_dir() == repo_default


def test_env_overrides_win_on_every_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _force_platform(monkeypatch, "darwin")
    monkeypatch.setenv("TRANSLATOR_CONFIG_DIR", str(tmp_path / "custom-cfg"))
    monkeypatch.setenv("TRANSLATOR_DB_DIR", str(tmp_path / "custom-db"))
    monkeypatch.setenv("TRANSLATOR_SOCKET_PATH", str(tmp_path / "s.sock"))
    monkeypatch.setenv("TRANSLATOR_LOG_DIR", str(tmp_path / "logs"))

    assert paths.config_dir() == tmp_path / "custom-cfg"
    assert paths.db_dir() == tmp_path / "custom-db"
    assert paths.socket_path() == tmp_path / "s.sock"
    assert paths.log_dir() == tmp_path / "logs"


def test_offline_base_resolution_prefers_existing_override_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _force_platform(monkeypatch, "darwin")
    override_dir = tmp_path / "override"
    override_dir.mkdir()
    (override_dir / "primary.sqlite3").write_bytes(b"x")
    monkeypatch.setenv("TRANSLATOR_DB_DIR", str(override_dir))

    assert locations.resolve_offline_base_file("primary.sqlite3") == (
        override_dir / "primary.sqlite3"
    )
    # Missing files fall back to the default directory instead of the repo tree.
    assert locations.resolve_offline_base_file("missing.sqlite3") == (
        override_dir / "missing.sqlite3"
    )


def test_offline_base_candidates_are_unique_and_ordered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _force_platform(monkeypatch, "darwin")
    monkeypatch.setenv("TRANSLATOR_DB_DIR", str(tmp_path / "db"))

    candidates = locations.offline_base_dir_candidates()

    assert candidates[0] == tmp_path / "db"
    assert (
        candidates[1]
        == tmp_path / "Library" / "Application Support" / "Translator" / "db"
    )
    assert len(candidates) == len(set(candidates))


def test_config_path_uses_platform_dir_on_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from desktop_app import config as config_module

    _force_platform(monkeypatch, "darwin")
    monkeypatch.setattr(config_module, "is_macos", lambda: True)

    expected = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Translator"
        / "desktop_config.json"
    )
    assert config_module.config_path() == expected
