from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import threading

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gdk", "4.0")
    require_version("GLib", "2.0")
Gdk = importlib.import_module("gi.repository.Gdk")
GLib = importlib.import_module("gi.repository.GLib")


class ClipboardWriter:
    def copy_text(self, text: str) -> None:
        if not text:
            return
        display = Gdk.Display.get_default()
        if display is not None:
            clipboard = display.get_clipboard()
            provider = Gdk.ContentProvider.new_for_bytes(
                "text/plain", GLib.Bytes.new(text.encode("utf-8"))
            )
            clipboard.set_content(provider)
            return
        self._copy_external(text)

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
        def _worker() -> None:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                process.communicate(input=text)
            except Exception:
                return

        threading.Thread(target=_worker, daemon=True).start()
        return True
