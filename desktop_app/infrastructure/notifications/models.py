from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NotificationLevel(Enum):
    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NotificationDuration(Enum):
    SHORT = 2000


@dataclass(frozen=True, slots=True)
class Notification:
    message: str
    level: NotificationLevel
    duration: NotificationDuration = NotificationDuration.SHORT
