from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import importlib
import threading
import uuid
from typing import TYPE_CHECKING, Final, TypeGuard

from dbus_next.aio.message_bus import MessageBus
from dbus_next.proxy_object import BaseProxyInterface
from dbus_next.signature import Variant

from desktop_app.hotkey import HotkeyBackend, HotkeyCallback, NotifyCallback

if TYPE_CHECKING:
    from desktop_app.gtk_types import GLib
else:
    import gi

    gi.require_version("GLib", "2.0")
    GLib = importlib.import_module("gi.repository.GLib")

PORTAL_SERVICE: Final[str] = "org.freedesktop.portal.Desktop"
PORTAL_PATH: Final[str] = "/org/freedesktop/portal/desktop"
GLOBAL_SHORTCUTS_IFACE: Final[str] = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_IFACE: Final[str] = "org.freedesktop.portal.Request"
SESSION_IFACE: Final[str] = "org.freedesktop.portal.Session"
SHORTCUT_ID: Final[str] = "translate"
SHORTCUT_DESCRIPTION: Final[str] = "Translate selection"
TOKEN_PREFIX: Final[str] = "translator"


@dataclass(frozen=True, slots=True)
class PortalResponse:
    code: int
    results: dict[str, Variant]


class PortalHotkeyBackend(HotkeyBackend):
    def __init__(
        self,
        *,
        app_id: str,
        preferred_trigger: str,
        parent_window: str,
        callback: HotkeyCallback,
        notify: NotifyCallback,
    ) -> None:
        super().__init__("portal", preferred_trigger, callback, notify)
        self._app_id = app_id
        self._parent_window = parent_window
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = False
        self._bus: MessageBus | None = None
        self._session_handle: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested = True
        if self._loop is None or self._stop_event is None:
            return
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._stop_event.set)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop_event = asyncio.Event()
        if self._stop_requested:
            self._stop_event.set()
        try:
            ready = loop.run_until_complete(self._setup())
            if not ready:
                return
            loop.run_until_complete(self._stop_event.wait())
        except Exception:
            self._notify_async("Portal hotkey backend unavailable.")
        finally:
            loop.run_until_complete(self._cleanup())
            loop.close()

    async def _setup(self) -> bool:
        try:
            self._bus = await MessageBus().connect()
        except Exception:
            self._notify_async("Portal hotkey backend unavailable.")
            return False
        portal = await self._get_portal_interface()
        if portal is None:
            self._notify_async("Portal hotkey backend unavailable.")
            return False
        portal.on_activated(self._on_activated)
        session_handle = await self._create_session(portal)
        if session_handle is None:
            return False
        self._session_handle = session_handle
        return await self._bind_shortcuts(portal, session_handle)

    async def _cleanup(self) -> None:
        if self._bus is None:
            return
        if self._session_handle is not None:
            try:
                intro = await self._bus.introspect(PORTAL_SERVICE, self._session_handle)
                proxy = self._bus.get_proxy_object(
                    PORTAL_SERVICE, self._session_handle, intro
                )
                session_iface = _SessionInterfaceAdapter(
                    proxy.get_interface(SESSION_IFACE)
                )
                await session_iface.call_close()
            except Exception:
                pass
        self._bus.disconnect()

    async def _get_portal_interface(self) -> _PortalInterfaceAdapter | None:
        if self._bus is None:
            return None
        try:
            intro = await self._bus.introspect(PORTAL_SERVICE, PORTAL_PATH)
        except Exception:
            return None
        proxy = self._bus.get_proxy_object(PORTAL_SERVICE, PORTAL_PATH, intro)
        return _PortalInterfaceAdapter(proxy.get_interface(GLOBAL_SHORTCUTS_IFACE))

    async def _create_session(self, portal: _PortalInterfaceAdapter) -> str | None:
        handle_token = _make_token("handle")
        session_token = _make_token("session")
        options = {
            "handle_token": Variant("s", handle_token),
            "session_handle_token": Variant("s", session_token),
        }
        request_handle = await portal.call_create_session(options)
        response = await self._await_request(request_handle)
        if response.code != 0:
            self._notify_async("Portal hotkey setup cancelled.")
            return None
        session_handle = _extract_session_handle(response)
        if session_handle is None:
            self._notify_async("Portal hotkey setup failed.")
        return session_handle

    async def _bind_shortcuts(
        self, portal: _PortalInterfaceAdapter, session_handle: str
    ) -> bool:
        shortcuts = [
            (
                SHORTCUT_ID,
                {
                    "description": Variant("s", SHORTCUT_DESCRIPTION),
                    "preferred_trigger": Variant("s", self.preferred_trigger),
                },
            )
        ]
        options = {"handle_token": Variant("s", _make_token("bind"))}
        request_handle = await portal.call_bind_shortcuts(
            session_handle, shortcuts, self._parent_window, options
        )
        response = await self._await_request(request_handle)
        if response.code != 0:
            self._notify_async("Portal hotkey binding cancelled.")
            return False
        return True

    async def _await_request(self, request_handle: str) -> PortalResponse:
        if self._bus is None:
            return PortalResponse(2, {})
        intro = await self._bus.introspect(PORTAL_SERVICE, request_handle)
        proxy = self._bus.get_proxy_object(PORTAL_SERVICE, request_handle, intro)
        request_iface = _RequestInterfaceAdapter(proxy.get_interface(REQUEST_IFACE))
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PortalResponse] = loop.create_future()

        def on_response(code: int, results: dict[str, Variant]) -> None:
            if future.done():
                return
            future.set_result(PortalResponse(code, results))

        request_iface.on_response(on_response)
        return await future

    def _on_activated(
        self,
        session_handle: str,
        shortcut_id: str,
        _timestamp: int,
        _options: dict[str, Variant],
    ) -> None:
        if self._session_handle is not None and session_handle != self._session_handle:
            return
        if shortcut_id != SHORTCUT_ID:
            return
        GLib.idle_add(self._dispatch_callback)

    def _dispatch_callback(self) -> bool:
        self._callback()
        return False

    def _notify_async(self, message: str) -> None:
        GLib.idle_add(self._dispatch_notify, message)

    def _dispatch_notify(self, message: str) -> bool:
        self._notify("Translator", message)
        return False


def _make_token(name: str) -> str:
    return f"{TOKEN_PREFIX}-{name}-{uuid.uuid4().hex}"


def _extract_session_handle(response: PortalResponse) -> str | None:
    value = response.results.get("session_handle")
    if isinstance(value, Variant):
        inner = value.value
        if isinstance(inner, str):
            return inner
    return None


class _PortalInterfaceAdapter:
    def __init__(self, iface: BaseProxyInterface) -> None:
        self._iface = iface

    def on_activated(
        self,
        handler: Callable[[str, str, int, dict[str, Variant]], None],
    ) -> None:
        callback = _require_callable(self._iface, "on_activated")
        callback(handler)

    async def call_create_session(self, options: dict[str, Variant]) -> str:
        method = _require_callable(self._iface, "call_create_session")
        result = method(options)
        return await _await_str(result)

    async def call_bind_shortcuts(
        self,
        session_handle: str,
        shortcuts: list[tuple[str, dict[str, Variant]]],
        parent_window: str,
        options: dict[str, Variant],
    ) -> str:
        method = _require_callable(self._iface, "call_bind_shortcuts")
        result = method(session_handle, shortcuts, parent_window, options)
        return await _await_str(result)


class _SessionInterfaceAdapter:
    def __init__(self, iface: BaseProxyInterface) -> None:
        self._iface = iface

    async def call_close(self) -> None:
        method = _require_callable(self._iface, "call_close")
        result = method()
        await _await_none(result)


class _RequestInterfaceAdapter:
    def __init__(self, iface: BaseProxyInterface) -> None:
        self._iface = iface

    def on_response(self, handler: Callable[[int, dict[str, Variant]], None]) -> None:
        callback = _require_callable(self._iface, "on_response")
        callback(handler)


def _require_callable(obj: object, name: str) -> Callable[..., object]:
    value = getattr(obj, name, None)
    if not _is_callable(value):
        raise RuntimeError(f"Missing portal method: {name}")
    return value


def _is_callable(value: object) -> TypeGuard[Callable[..., object]]:
    return callable(value)


async def _await_str(value: object) -> str:
    if not isinstance(value, Awaitable):
        raise RuntimeError("Portal call returned unexpected value")
    return await _await_str_from_awaitable(value)


async def _await_none(value: object) -> None:
    if not isinstance(value, Awaitable):
        raise RuntimeError("Portal call returned unexpected value")
    await _await_none_from_awaitable(value)


async def _await_str_from_awaitable(value: Awaitable[object]) -> str:
    resolved = await value
    if isinstance(resolved, str):
        return resolved
    raise RuntimeError("Portal call returned unexpected value")


async def _await_none_from_awaitable(value: Awaitable[object]) -> None:
    resolved = await value
    if resolved is None:
        return
    raise RuntimeError("Portal call returned unexpected value")
