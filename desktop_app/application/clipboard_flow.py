from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from desktop_app.application.ports import ClipboardPort, ClipboardReadStatus


class ClipboardError(Enum):
    NO_TEXT = "no_text"
    NO_DISPLAY = "no_display"
    NO_CLIPBOARD = "no_clipboard"


@dataclass(slots=True)
class ClipboardFlow:
    clipboard: ClipboardPort

    def request_text(
        self,
        *,
        hotkey: bool,
        on_text: Callable[[str], None],
        on_error: Callable[[ClipboardError], None],
    ) -> None:
        def start_primary_read() -> None:
            status = self.clipboard.read_primary(handle_primary)
            if status is ClipboardReadStatus.NO_DISPLAY:
                on_error(ClipboardError.NO_DISPLAY)
            elif status is ClipboardReadStatus.NO_CLIPBOARD:
                on_error(ClipboardError.NO_CLIPBOARD)

        def handle_primary(text: str | None) -> None:
            if text and text.strip():
                on_text(text)
                return
            on_error(ClipboardError.NO_TEXT)

        def handle_wayland_primary(text: str | None) -> None:
            if text and text.strip():
                on_text(text)
                return
            start_primary_read()

        if hotkey and self.clipboard.read_wayland_primary_async(handle_wayland_primary):
            return

        start_primary_read()
