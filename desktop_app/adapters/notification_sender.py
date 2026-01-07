from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from desktop_app.gtk_types import Gio
else:
    import gi

    gi.require_version("Gio", "2.0")
    Gio = importlib.import_module("gi.repository.Gio")


class GioApplication(Protocol):
    def send_notification(self, id: str | None, notification: Gio.Notification) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class NotificationSender:
    app: GioApplication | None
    use_gio: bool
    icon_path: Path

    def send(self, title: str, body: str) -> None:
        if self.use_gio and self.app is not None:
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            self.app.send_notification(None, notification)
            return
        self._notify_send(title, body)

    def _notify_send(self, title: str, body: str) -> None:
        command = [
            "notify-send",
            "--app-name=Translator",
            "--hint=string:desktop-entry:com.translator.desktop",
        ]
        if self.icon_path.exists():
            command.extend(["--icon", str(self.icon_path)])
        command.extend([title, body])
        try:
            subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return
