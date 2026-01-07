from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import importlib
import os
from typing import TYPE_CHECKING

from desktop_app.config import HotkeyBackend, HotkeyConfig, detect_hotkey_backend
from desktop_app.hotkey import HotkeyBackend as HotkeyBackendImpl, create_hotkey_backend
from desktop_app.hotkey.core import HotkeyCallback, NotifyCallback

if TYPE_CHECKING:
    from desktop_app.gtk_types import Gdk, Gtk
else:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    Gdk = importlib.import_module("gi.repository.Gdk")
    Gtk = importlib.import_module("gi.repository.Gtk")


@dataclass(slots=True)
class HotkeyManager:
    app_id: str
    notify: NotifyCallback
    callback: HotkeyCallback
    hotkey_provider: Callable[[], HotkeyConfig]
    backend: HotkeyBackendImpl | None = None
    portal_handle: str | None = None
    pending: bool = False

    def ensure_started(self) -> None:
        if self.backend is None:
            self.start()

    def start(self) -> None:
        backend = self.runtime_backend()
        self.pending = False
        if backend is HotkeyBackend.PORTAL and self.portal_handle is None:
            self.pending = True
            return
        self.backend = self._create_backend_for(backend)
        try:
            self.backend.start()
            return
        except Exception:
            self.notify("Translator", "Hotkey backend failed, falling back.")
        fallback = self._fallback_hotkey_backend(backend)
        if fallback is backend:
            return
        self.backend = self._create_backend_for(fallback)
        try:
            self.backend.start()
        except Exception:
            self.notify("Translator", "Hotkey backend unavailable.")

    def stop(self) -> None:
        if self.backend is not None:
            self.backend.stop()
        self.backend = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def update_portal_handle(self, handle: str | None) -> None:
        if handle is None or handle == self.portal_handle:
            return
        self.portal_handle = handle
        if self.pending and self.backend is None:
            self.pending = False
            self.start()

    def runtime_backend(self) -> HotkeyBackend:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").casefold()
        if "gnome" in desktop:
            return HotkeyBackend.GNOME
        display = Gdk.Display.get_default()
        if display is None:
            return detect_hotkey_backend()
        name = ""
        if hasattr(display, "get_name"):
            name = display.get_name().casefold()
        if "wayland" in name:
            return HotkeyBackend.PORTAL
        if "x11" in name:
            return HotkeyBackend.X11
        return detect_hotkey_backend()

    def _create_backend_for(self, backend: HotkeyBackend) -> HotkeyBackendImpl:
        preferred_trigger = self._preferred_trigger(
            backend, self.hotkey_provider().trigger
        )
        return create_hotkey_backend(
            app_id=self.app_id,
            backend=backend.value,
            preferred_trigger=preferred_trigger,
            parent_window=self.portal_handle,
            callback=self.callback,
            notify=self.notify,
        )

    def _fallback_hotkey_backend(self, backend: HotkeyBackend) -> HotkeyBackend:
        session = os.environ.get("XDG_SESSION_TYPE", "").casefold()
        has_display = bool(os.environ.get("DISPLAY"))
        if backend is HotkeyBackend.GNOME:
            if session == "wayland":
                return HotkeyBackend.PORTAL
            if has_display:
                return HotkeyBackend.X11
        if backend is HotkeyBackend.PORTAL:
            if has_display:
                return HotkeyBackend.X11
        return HotkeyBackend.SYSTEM

    def _preferred_trigger(self, backend: HotkeyBackend, trigger: str) -> str:
        if backend is not HotkeyBackend.PORTAL:
            return trigger
        parsed = self._parse_trigger(trigger)
        if parsed is None:
            return trigger
        keyval, modifiers = parsed
        accel = Gtk.accelerator_name(keyval, modifiers)
        return accel or trigger

    def _parse_trigger(self, trigger: str) -> tuple[int, int] | None:
        parts = [part.strip() for part in trigger.split("+") if part.strip()]
        if not parts:
            return None
        modifiers = 0
        key_name = ""
        for part in parts:
            name = part.casefold()
            if name in {"ctrl", "control"}:
                modifiers |= Gdk.ModifierType.CONTROL_MASK
            elif name == "shift":
                modifiers |= Gdk.ModifierType.SHIFT_MASK
            elif name == "alt":
                alt_mask = getattr(
                    Gdk.ModifierType,
                    "ALT_MASK",
                    getattr(Gdk.ModifierType, "MOD1_MASK", 0),
                )
                modifiers |= alt_mask
            elif name == "super":
                modifiers |= Gdk.ModifierType.SUPER_MASK
            elif name == "meta":
                modifiers |= Gdk.ModifierType.META_MASK
            else:
                key_name = part
        if not key_name:
            return None
        keyval = Gdk.keyval_from_name(key_name)
        if keyval == 0:
            keyval = Gdk.keyval_from_name(key_name.upper())
        if keyval == 0:
            return None
        return keyval, modifiers
