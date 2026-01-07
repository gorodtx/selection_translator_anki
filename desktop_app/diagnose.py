from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
import os
import sys
from typing import Final

PORTAL_SERVICE: Final[str] = "org.freedesktop.portal.Desktop"
PORTAL_PATH: Final[str] = "/org/freedesktop/portal/desktop"
TIMEOUT_SECONDS: Final[float] = 2.0


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    ok: bool
    detail: str


def main() -> None:
    results = _run_diagnostics()
    for result in results:
        status = "ok" if result.ok else "fail"
        print(f"{result.name}: {status} - {result.detail}")


def _run_diagnostics() -> list[ProbeResult]:
    results: list[ProbeResult] = []
    results.append(ProbeResult("platform", True, sys.platform))
    results.append(ProbeResult("session_type", True, _session_type_label()))
    results.append(
        ProbeResult(
            "env_display", _is_x11(), f"DISPLAY={os.environ.get('DISPLAY', '')}"
        )
    )
    results.append(
        ProbeResult(
            "env_wayland",
            _is_wayland(),
            f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '')}",
        )
    )
    dbus_next_ok = _has_module("dbus_next")
    xlib_ok = _has_module("Xlib")
    results.append(
        ProbeResult(
            "portal_dep",
            dbus_next_ok,
            "dbus-next installed" if dbus_next_ok else "dbus-next missing",
        )
    )
    results.append(
        ProbeResult(
            "x11_dep",
            xlib_ok,
            "python-xlib installed" if xlib_ok else "python-xlib missing",
        )
    )
    portal_ok, portal_detail = _probe_portal(dbus_next_ok)
    results.append(ProbeResult("portal_service", portal_ok, portal_detail))
    recommended = _recommend_backend(
        is_linux=sys.platform.startswith("linux"),
        is_wayland=_is_wayland(),
        portal_ok=portal_ok,
        is_x11=_is_x11(),
        x11_ok=xlib_ok,
    )
    results.append(ProbeResult("backend_auto", True, recommended))
    return results


def _probe_portal(dbus_next_ok: bool) -> tuple[bool, str]:
    if not sys.platform.startswith("linux"):
        return False, "not on linux"
    if not dbus_next_ok:
        return False, "dbus-next missing"
    try:
        return asyncio.run(_probe_portal_async())
    except Exception as exc:
        return False, f"portal error: {exc}"


async def _probe_portal_async() -> tuple[bool, str]:
    try:
        from dbus_next.aio.message_bus import MessageBus
    except Exception as exc:
        return False, f"dbus-next import failed: {exc}"
    try:
        bus = await asyncio.wait_for(MessageBus().connect(), timeout=TIMEOUT_SECONDS)
    except Exception as exc:
        return False, f"session bus error: {exc}"
    try:
        await asyncio.wait_for(
            bus.introspect(PORTAL_SERVICE, PORTAL_PATH),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:
        bus.disconnect()
        return False, f"portal introspect failed: {exc}"
    bus.disconnect()
    return True, "portal ok"


def _recommend_backend(
    *,
    is_linux: bool,
    is_wayland: bool,
    portal_ok: bool,
    is_x11: bool,
    x11_ok: bool,
) -> str:
    override = os.environ.get("TRANSLATOR_HOTKEY_BACKEND", "").strip().lower()
    if override:
        return override
    if is_linux and is_wayland and portal_ok:
        return "portal"
    if is_linux and is_x11 and x11_ok:
        return "x11"
    return "system"


def _has_module(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _is_wayland() -> bool:
    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or "WAYLAND_DISPLAY" in os.environ
    )


def _is_x11() -> bool:
    return bool(os.environ.get("DISPLAY"))


def _session_type_label() -> str:
    value = os.environ.get("XDG_SESSION_TYPE", "")
    if value:
        return value
    if _is_wayland():
        return "wayland"
    if _is_x11():
        return "x11"
    return "unknown"


if __name__ == "__main__":
    main()
