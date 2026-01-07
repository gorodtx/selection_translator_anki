from __future__ import annotations

import importlib
import threading
import time
from typing import TYPE_CHECKING, Final, Protocol

from Xlib import X, XK, display

from desktop_app.hotkey import HotkeyBackend, HotkeyCallback, NotifyCallback

if TYPE_CHECKING:
    from desktop_app.gtk_types import GLib
else:
    import gi

    gi.require_version("GLib", "2.0")
    GLib = importlib.import_module("gi.repository.GLib")

MODIFIER_MAP: Final[dict[str, int]] = {
    "ctrl": X.ControlMask,
    "control": X.ControlMask,
    "alt": X.Mod1Mask,
    "shift": X.ShiftMask,
    "super": X.Mod4Mask,
    "meta": X.Mod4Mask,
}

EXTRA_MODIFIER_MASKS: Final[tuple[int, int, int, int]] = (
    0,
    X.LockMask,
    X.Mod2Mask,
    X.LockMask | X.Mod2Mask,
)

POLL_INTERVAL_SECONDS: Final[float] = 0.05


class X11HotkeyBackend(HotkeyBackend):
    def __init__(
        self,
        preferred_trigger: str,
        callback: HotkeyCallback,
        notify: NotifyCallback,
    ) -> None:
        super().__init__("x11", preferred_trigger, callback, notify)
        self._display: display.Display | None = None
        self._root: _RootWindow | None = None
        self._keycode: int | None = None
        self._modifiers = 0
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            self._display = display.Display()
        except Exception:
            self._notify("Translator", "X11 display not available.")
            return
        self._root = self._display.screen().root
        try:
            self._keycode, self._modifiers = self._parse_hotkey(self.preferred_trigger)
        except ValueError:
            self._notify("Translator", "Invalid hotkey format.")
            self._display.close()
            self._display = None
            self._root = None
            return
        self._grab_keys()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._display is None or self._root is None or self._keycode is None:
            return
        for extra in EXTRA_MODIFIER_MASKS:
            self._root.ungrab_key(self._keycode, self._modifiers | extra)
        self._display.flush()
        self._display.close()

    def _parse_hotkey(self, trigger: str) -> tuple[int, int]:
        parts = [part.strip() for part in trigger.split("+") if part.strip()]
        if not parts:
            raise ValueError
        modifiers = 0
        key_name = ""
        for part in parts:
            name = part.casefold()
            if name in MODIFIER_MAP:
                modifiers |= MODIFIER_MAP[name]
            else:
                key_name = part
        if not key_name:
            raise ValueError
        keysym = XK.string_to_keysym(key_name)
        if keysym == 0:
            keysym = XK.string_to_keysym(key_name.upper())
        if keysym == 0:
            raise ValueError
        if self._display is None:
            raise ValueError
        keycode = self._display.keysym_to_keycode(keysym)
        if keycode == 0:
            raise ValueError
        return keycode, modifiers

    def _grab_keys(self) -> None:
        if self._display is None or self._root is None or self._keycode is None:
            return
        for extra in EXTRA_MODIFIER_MASKS:
            self._root.grab_key(
                self._keycode,
                self._modifiers | extra,
                True,
                X.GrabModeAsync,
                X.GrabModeAsync,
            )
        self._display.flush()

    def _run_loop(self) -> None:
        if self._display is None or self._keycode is None:
            return
        while self._running:
            try:
                if self._display.pending_events():
                    event = self._display.next_event()
                    if event.type == X.KeyPress and event.detail == self._keycode:
                        if (event.state & self._modifiers) == self._modifiers:
                            GLib.idle_add(self._dispatch_callback)
                else:
                    time.sleep(POLL_INTERVAL_SECONDS)
            except Exception:
                break

    def _dispatch_callback(self) -> bool:
        self._callback()
        return False


class _RootWindow(Protocol):
    def grab_key(
        self,
        key: int,
        modifiers: int,
        owner_events: bool,
        pointer_mode: int,
        keyboard_mode: int,
    ) -> None: ...

    def ungrab_key(self, key: int, modifiers: int) -> None: ...
