from __future__ import annotations

from typing import TYPE_CHECKING

from desktop_app.infrastructure.notifications.models import Notification as Notification
from desktop_app.infrastructure.notifications.models import (
    NotificationDuration as NotificationDuration,
)
from desktop_app.infrastructure.notifications.models import (
    NotificationLevel as NotificationLevel,
)

if TYPE_CHECKING:
    from desktop_app.infrastructure.notifications.banner import BannerHost as BannerHost


def __getattr__(name: str) -> object:
    # BannerHost pulls in GTK; resolve it lazily so headless runtimes (macOS
    # daemon, tests without PyGObject) can import the notification models.
    if name == "BannerHost":
        from desktop_app.infrastructure.notifications.banner import BannerHost

        return BannerHost
    raise AttributeError(name)
