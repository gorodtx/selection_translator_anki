from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NotificationKind(Enum):
    INFO = "info"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    title: str
    body: str
    kind: NotificationKind = NotificationKind.INFO
