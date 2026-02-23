from __future__ import annotations

import os

DEFAULT_APP_ID = "com.translator.desktop"
DEFAULT_DBUS_INTERFACE = "com.translator.desktop"
DEFAULT_DBUS_OBJECT_PATH = "/com/translator/desktop"
DEFAULT_RUNTIME_NAMESPACE = "translator"


def app_id() -> str:
    value = os.environ.get("TRANSLATOR_APP_ID", "").strip()
    return value or DEFAULT_APP_ID


def dbus_interface() -> str:
    value = os.environ.get("TRANSLATOR_DBUS_INTERFACE", "").strip()
    return value or DEFAULT_DBUS_INTERFACE


def dbus_object_path() -> str:
    value = os.environ.get("TRANSLATOR_DBUS_OBJECT_PATH", "").strip()
    return value or DEFAULT_DBUS_OBJECT_PATH


def runtime_namespace() -> str:
    value = os.environ.get("TRANSLATOR_RUNTIME_NAMESPACE", "").strip()
    return value or DEFAULT_RUNTIME_NAMESPACE
