from __future__ import annotations

from desktop_app import runtime_namespace


def test_defaults(monkeypatch) -> None:
    monkeypatch.delenv("TRANSLATOR_APP_ID", raising=False)
    monkeypatch.delenv("TRANSLATOR_DBUS_INTERFACE", raising=False)
    monkeypatch.delenv("TRANSLATOR_DBUS_OBJECT_PATH", raising=False)
    monkeypatch.delenv("TRANSLATOR_RUNTIME_NAMESPACE", raising=False)

    assert runtime_namespace.app_id() == "com.translator.desktop"
    assert runtime_namespace.dbus_interface() == "com.translator.desktop"
    assert runtime_namespace.dbus_object_path() == "/com/translator/desktop"
    assert runtime_namespace.runtime_namespace() == "translator"


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("TRANSLATOR_APP_ID", "com.translator.desktop.dev")
    monkeypatch.setenv("TRANSLATOR_DBUS_INTERFACE", "com.translator.desktop")
    monkeypatch.setenv("TRANSLATOR_DBUS_OBJECT_PATH", "/com/translator/desktop")
    monkeypatch.setenv("TRANSLATOR_RUNTIME_NAMESPACE", "translator-dev")

    assert runtime_namespace.app_id() == "com.translator.desktop.dev"
    assert runtime_namespace.dbus_interface() == "com.translator.desktop"
    assert runtime_namespace.dbus_object_path() == "/com/translator/desktop"
    assert runtime_namespace.runtime_namespace() == "translator-dev"
