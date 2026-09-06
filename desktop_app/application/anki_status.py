from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnkiStatus:
    model_status: str
    deck_status: str
    deck_name: str


@dataclass(frozen=True, slots=True)
class AnkiActionResult:
    message: str
    status: AnkiStatus
