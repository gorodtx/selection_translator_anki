from __future__ import annotations

import os
from pathlib import Path

from desktop_app import config
from desktop_app.platform import paths


def test_user_config_home_windows_appdata(monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\den\AppData\Roaming")

    resolved = paths.user_config_home()

    assert resolved == Path(r"C:\Users\den\AppData\Roaming")


def test_runtime_state_home_windows_localappdata(monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\den\AppData\Local")

    resolved = paths.runtime_state_home("translator-dev")

    assert resolved == Path(r"C:\Users\den\AppData\Local") / "translator-dev"


def test_config_path_windows_appdata(monkeypatch) -> None:
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\den\AppData\Roaming")

    resolved = config.config_path()

    assert resolved == Path(r"C:\Users\den\AppData\Roaming") / "translator" / "desktop_config.json"


def test_config_path_linux_prefers_newer_xdg_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config.sys, "platform", "linux")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    xdg_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))

    default_path = home / ".config" / "translator" / "desktop_config.json"
    xdg_path = xdg_home / "translator" / "desktop_config.json"
    default_path.parent.mkdir(parents=True, exist_ok=True)
    xdg_path.parent.mkdir(parents=True, exist_ok=True)
    default_path.write_text("{}", encoding="utf-8")
    xdg_path.write_text("{\"languages\":{}}", encoding="utf-8")
    os.utime(default_path, (10, 10))
    os.utime(xdg_path, (20, 20))

    resolved = config.config_path()

    assert resolved == xdg_path
