from __future__ import annotations

from collections.abc import Callable
from typing import Final

HotkeyCallback = Callable[[], None]
NotifyCallback = Callable[[str, str], None]

BACKEND_SYSTEM: Final[str] = "system"
BACKEND_PORTAL: Final[str] = "portal"
BACKEND_X11: Final[str] = "x11"
BACKEND_GNOME: Final[str] = "gnome"


class HotkeyBackend:
    def __init__(
        self,
        name: str,
        preferred_trigger: str,
        callback: HotkeyCallback,
        notify: NotifyCallback,
    ) -> None:
        self.name = name
        self.preferred_trigger = preferred_trigger
        self._callback = callback
        self._notify = notify

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


def create_hotkey_backend(
    *,
    app_id: str,
    backend: str,
    preferred_trigger: str,
    parent_window: str | None = None,
    callback: HotkeyCallback,
    notify: NotifyCallback,
) -> HotkeyBackend:
    choice = backend.strip().lower()
    if choice == BACKEND_SYSTEM:
        return _create_system_backend(preferred_trigger, callback, notify)
    if choice == BACKEND_PORTAL:
        return _create_portal_backend(
            app_id,
            preferred_trigger,
            parent_window,
            callback,
            notify,
            notify_unavailable=True,
        )
    if choice == BACKEND_GNOME:
        return _create_gnome_backend(preferred_trigger, callback, notify)
    if choice == BACKEND_X11:
        return _create_x11_backend(
            preferred_trigger, callback, notify, notify_unavailable=True
        )
    return _create_system_backend(preferred_trigger, callback, notify)


def _create_system_backend(
    preferred_trigger: str,
    callback: HotkeyCallback,
    notify: NotifyCallback,
) -> HotkeyBackend:
    from desktop_app.hotkey.system import SystemHotkeyBackend

    return SystemHotkeyBackend(preferred_trigger, callback, notify)


def _create_portal_backend(
    app_id: str,
    preferred_trigger: str,
    parent_window: str | None,
    callback: HotkeyCallback,
    notify: NotifyCallback,
    *,
    notify_unavailable: bool,
) -> HotkeyBackend:
    if not _is_linux():
        return _create_system_backend(preferred_trigger, callback, notify)
    try:
        from desktop_app.hotkey.portal import PortalHotkeyBackend
    except Exception:
        if notify_unavailable:
            notify("Translator", "Portal hotkey backend unavailable.")
        return _create_system_backend(preferred_trigger, callback, notify)
    return PortalHotkeyBackend(
        app_id=app_id,
        preferred_trigger=preferred_trigger,
        parent_window=parent_window or "",
        callback=callback,
        notify=notify,
    )


def _create_gnome_backend(
    preferred_trigger: str,
    callback: HotkeyCallback,
    notify: NotifyCallback,
) -> HotkeyBackend:
    if not _is_linux():
        return _create_system_backend(preferred_trigger, callback, notify)
    try:
        from desktop_app.hotkey.gnome import GnomeHotkeyBackend
    except Exception:
        notify("Translator", "GNOME hotkey backend unavailable.")
        return _create_system_backend(preferred_trigger, callback, notify)
    return GnomeHotkeyBackend(preferred_trigger, callback, notify)


def _create_x11_backend(
    preferred_trigger: str,
    callback: HotkeyCallback,
    notify: NotifyCallback,
    *,
    notify_unavailable: bool,
) -> HotkeyBackend:
    if not _is_linux():
        return _create_system_backend(preferred_trigger, callback, notify)
    try:
        from desktop_app.hotkey.x11 import X11HotkeyBackend
    except Exception:
        if notify_unavailable:
            notify("Translator", "X11 hotkey backend unavailable.")
        return _create_system_backend(preferred_trigger, callback, notify)
    return X11HotkeyBackend(preferred_trigger, callback, notify)


def _is_linux() -> bool:
    import sys

    return sys.platform.startswith("linux")
