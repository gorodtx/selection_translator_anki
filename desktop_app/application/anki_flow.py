from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum

from desktop_app.anki import AnkiAddResult, AnkiCreateModelResult, AnkiListResult
from desktop_app.application.ports import AnkiPort
from desktop_app.config import AnkiConfig
from translate_logic.models import TranslationResult


class AnkiOutcome(Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AnkiResult:
    outcome: AnkiOutcome
    message: str | None = None


@dataclass(slots=True)
class AnkiFlow:
    service: AnkiPort

    def refresh_decks(self) -> Future[AnkiListResult]:
        return self.service.deck_names()

    def model_names(self) -> Future[AnkiListResult]:
        return self.service.model_names()

    def is_config_ready(self, config: AnkiConfig) -> bool:
        fields = config.fields
        return all(
            [
                config.deck,
                config.model,
                fields.word,
                fields.ipa,
                fields.translation,
                fields.example_en,
                fields.example_ru,
            ]
        )

    def build_fields(
        self, config: AnkiConfig, original_text: str, result: TranslationResult
    ) -> dict[str, str]:
        fields = config.fields
        return {
            fields.word: original_text,
            fields.ipa: result.ipa_uk.text,
            fields.translation: result.translation_ru.text,
            fields.example_en: result.example_en.text,
            fields.example_ru: result.example_ru.text,
        }

    def add_note(
        self,
        config: AnkiConfig,
        original_text: str,
        result: TranslationResult,
        on_done: Callable[[AnkiResult], None],
        *,
        on_unavailable: Callable[[], None] | None = None,
    ) -> Future[AnkiAddResult]:
        fields = self.build_fields(config, original_text, result)
        future = self.service.add_note(config.deck, config.model, fields)
        future.add_done_callback(
            lambda done: self._handle_add_result(done, on_done, on_unavailable)
        )
        return future

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]:
        return self.service.create_model(model_name, fields, front, back, css)

    def _handle_add_result(
        self,
        future: Future[AnkiAddResult],
        on_done: Callable[[AnkiResult], None],
        on_unavailable: Callable[[], None] | None,
    ) -> None:
        if future.cancelled():
            return
        try:
            result = future.result()
        except Exception:
            on_done(AnkiResult(outcome=AnkiOutcome.ERROR, message=None))
            return
        if result.success:
            on_done(AnkiResult(outcome=AnkiOutcome.SUCCESS, message=None))
            return
        message = result.error or "Failed to add card."
        if "duplicate" in message.casefold():
            on_done(AnkiResult(outcome=AnkiOutcome.DUPLICATE, message=message))
            return
        if "ankiconnect error" in message.casefold():
            if on_unavailable is not None:
                on_unavailable()
            on_done(AnkiResult(outcome=AnkiOutcome.UNAVAILABLE, message=message))
            return
        on_done(AnkiResult(outcome=AnkiOutcome.ERROR, message=message))
