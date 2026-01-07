from __future__ import annotations

from desktop_app.hotkey import HotkeyBackend, HotkeyCallback, NotifyCallback


class SystemHotkeyBackend(HotkeyBackend):
    def __init__(
        self,
        preferred_trigger: str,
        callback: HotkeyCallback,
        notify: NotifyCallback,
    ) -> None:
        super().__init__("system", preferred_trigger, callback, notify)

    def start(self) -> None:
        return

    def stop(self) -> None:
        return
