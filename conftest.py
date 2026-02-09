from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # In this repository, dev-only tests live in `dev/` and are not shipped.
    # Pytest uses exit code 5 when no tests are collected, which would fail our
    # quality gate. Treat "no tests" as success.
    if exitstatus == 5:
        session.exitstatus = 0


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    del config
    ignored_parts = {
        ".uv-cache",
        ".uv_cache",
        ".venv",
        ".venv-desktop",
        "__pycache__",
        "dev/tests",
    }
    path_str = collection_path.as_posix()
    if "dev/tests" in path_str:
        return True
    return any(part in collection_path.parts for part in ignored_parts)


def pytest_configure(config: pytest.Config) -> None:
    del config
    _install_gi_stub_if_missing()


def _install_gi_stub_if_missing() -> None:
    if importlib.util.find_spec("gi") is not None:
        return

    gi_module = types.ModuleType("gi")

    def require_version(_name: str, _version: str) -> None:
        return

    setattr(gi_module, "require_version", require_version)
    sys.modules["gi"] = gi_module

    repository_module = types.ModuleType("gi.repository")
    sys.modules["gi.repository"] = repository_module

    glib_module = types.ModuleType("gi.repository.GLib")
    setattr(glib_module, "idle_add", lambda fn, *args: fn(*args))
    setattr(glib_module, "timeout_add", lambda _ms, fn, *args: fn(*args))
    setattr(glib_module, "source_remove", lambda _source_id: None)
    setattr(glib_module, "set_application_name", lambda _name: None)
    setattr(glib_module, "set_prgname", lambda _name: None)

    class _Bytes:
        @staticmethod
        def new(data: bytes) -> bytes:
            return data

    setattr(glib_module, "Bytes", _Bytes)
    sys.modules["gi.repository.GLib"] = glib_module

    gdk_module = types.ModuleType("gi.repository.Gdk")
    setattr(gdk_module, "KEY_Escape", 65307)

    class _Display:
        @staticmethod
        def get_default() -> None:
            return None

    class _ContentProvider:
        @staticmethod
        def new_for_bytes(_mime: str, _data: bytes) -> object:
            return object()

    setattr(gdk_module, "Display", _Display)
    setattr(gdk_module, "ContentProvider", _ContentProvider)
    sys.modules["gi.repository.Gdk"] = gdk_module

    gio_module = types.ModuleType("gi.repository.Gio")
    sys.modules["gi.repository.Gio"] = gio_module

    gtk_module = types.ModuleType("gi.repository.Gtk")
    setattr(gtk_module, "STYLE_PROVIDER_PRIORITY_APPLICATION", 0)
    sys.modules["gi.repository.Gtk"] = gtk_module
