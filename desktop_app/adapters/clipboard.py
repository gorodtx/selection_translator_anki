from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import threading
from typing import TYPE_CHECKING, Callable

from desktop_app.application.ports import ClipboardPort, ClipboardReadStatus

if TYPE_CHECKING:
    from desktop_app.gtk_types import Gdk, Gio, GLib
else:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    Gdk = importlib.import_module("gi.repository.Gdk")
    Gio = importlib.import_module("gi.repository.Gio")
    GLib = importlib.import_module("gi.repository.GLib")


class ClipboardAdapter(ClipboardPort):
    def read_wayland_primary(self) -> str | None:
        if not sys_platform_is_linux():
            return None
        session = os.environ.get("XDG_SESSION_TYPE", "").casefold()
        if session != "wayland":
            return None
        cmd = shutil.which("wl-paste")
        if cmd is None:
            return None
        try:
            result = subprocess.run(
                [cmd, "--primary", "--no-newline"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.2,
            )
        except Exception:
            return None
        return result.stdout

    def read_wayland_primary_async(
        self, callback: Callable[[str | None], None]
    ) -> bool:
        if not sys_platform_is_linux():
            return False
        session = os.environ.get("XDG_SESSION_TYPE", "").casefold()
        if session != "wayland":
            return False
        cmd = shutil.which("wl-paste")
        if cmd is None:
            return False

        def worker() -> None:
            text = self.read_wayland_primary()
            GLib.idle_add(_dispatch_text, callback, text)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return True

    def read_primary(
        self, callback: Callable[[str | None], None]
    ) -> ClipboardReadStatus:
        display = Gdk.Display.get_default()
        if display is None:
            return ClipboardReadStatus.NO_DISPLAY
        primary = display.get_primary_clipboard()
        if primary is None:
            return ClipboardReadStatus.NO_CLIPBOARD
        primary.read_text_async(None, self._on_text_ready, callback)
        return ClipboardReadStatus.STARTED

    def _on_text_ready(
        self,
        clipboard: Gdk.Clipboard,
        result: Gio.AsyncResult,
        callback: Callable[[str | None], None],
    ) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except Exception:
            text = None
        callback(text)


def _dispatch_text(callback: Callable[[str | None], None], text: str | None) -> bool:
    callback(text)
    return False


def sys_platform_is_linux() -> bool:
    import sys

    return sys.platform.startswith("linux")
