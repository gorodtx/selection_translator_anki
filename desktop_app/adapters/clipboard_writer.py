from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desktop_app.gtk_types import Gdk, GLib
else:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("GLib", "2.0")
    Gdk = importlib.import_module("gi.repository.Gdk")
    GLib = importlib.import_module("gi.repository.GLib")


class ClipboardWriter:
    def copy_text(self, text: str) -> None:
        if not text:
            return
        if self._copy_external(text):
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        clipboard = display.get_clipboard()
        provider = Gdk.ContentProvider.new_for_bytes(
            "text/plain", GLib.Bytes.new(text.encode("utf-8"))
        )
        clipboard.set_content(provider)

    def _copy_external(self, text: str) -> bool:
        session = os.environ.get("XDG_SESSION_TYPE", "").casefold()
        if session == "wayland":
            cmd = shutil.which("wl-copy")
            if cmd is None:
                return False
            return self._run_clipboard_command([cmd, "--type", "text/plain"], text)
        cmd = shutil.which("xclip")
        if cmd is not None:
            return self._run_clipboard_command([cmd, "-selection", "clipboard"], text)
        cmd = shutil.which("xsel")
        if cmd is not None:
            return self._run_clipboard_command([cmd, "--clipboard", "--input"], text)
        return False

    def _run_clipboard_command(self, command: list[str], text: str) -> bool:
        try:
            subprocess.run(
                command,
                input=text,
                check=False,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.5,
            )
        except Exception:
            return False
        return True
