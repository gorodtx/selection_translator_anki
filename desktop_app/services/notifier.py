from __future__ import annotations

from collections.abc import Callable

from desktop_app.application.notifications import NotificationMessage


class Notifier:
    def __init__(self, send: Callable[[str, str], None]) -> None:
        self._send = send

    def send(self, message: NotificationMessage) -> None:
        self._send(message.title, message.body)
