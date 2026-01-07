from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from enum import Enum
from typing import Protocol

from desktop_app.application.history import HistoryItem
from desktop_app.anki import AnkiAddResult, AnkiCreateModelResult, AnkiListResult
from desktop_app.application.notifications import NotificationMessage
from translate_logic.models import TranslationResult


class TranslatorPort(Protocol):
    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]: ...


class HistoryPort(Protocol):
    def add(self, text: str, result: TranslationResult) -> None: ...

    def snapshot(self) -> list[HistoryItem]: ...


class ClipboardReadStatus(Enum):
    STARTED = "started"
    NO_DISPLAY = "no_display"
    NO_CLIPBOARD = "no_clipboard"


class ClipboardPort(Protocol):
    def read_wayland_primary(self) -> str | None: ...

    def read_wayland_primary_async(
        self, callback: Callable[[str | None], None]
    ) -> bool: ...

    def read_primary(
        self, callback: Callable[[str | None], None]
    ) -> ClipboardReadStatus: ...


class NotifierPort(Protocol):
    def send(self, message: NotificationMessage) -> None: ...


class AnkiPort(Protocol):
    def deck_names(self) -> Future[AnkiListResult]: ...

    def model_names(self) -> Future[AnkiListResult]: ...

    def add_note(
        self, deck: str, model: str, fields: dict[str, str]
    ) -> Future[AnkiAddResult]: ...

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]: ...
