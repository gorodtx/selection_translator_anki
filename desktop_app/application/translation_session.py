from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from translate_logic.models import (
    TranslationResult,
    TranslationStatus,
    TranslationVariant,
)


@dataclass(slots=True)
class TranslationSession:
    start_translation: Callable[
        [str, Callable[[TranslationResult], None]], Future[TranslationResult]
    ]
    on_start: Callable[[str], None]
    on_partial: Callable[[TranslationResult], None]
    on_complete: Callable[[TranslationResult], None]
    on_error: Callable[[], None]

    def run(self, display_text: str, query_text: str) -> Future[TranslationResult]:
        self.on_start(display_text)

        def handle_partial(result: TranslationResult) -> None:
            if result.status is not TranslationStatus.SUCCESS:
                return
            stripped_variants = tuple(
                TranslationVariant(
                    ru=variant.ru,
                    pos=variant.pos,
                    synonyms=variant.synonyms,
                    examples=(),
                    source=variant.source,
                )
                for variant in result.variants
            )
            self.on_partial(TranslationResult(variants=stripped_variants))

        future = self.start_translation(query_text, handle_partial)
        future.add_done_callback(self._handle_done)
        return future

    def _handle_done(self, future: Future[TranslationResult]) -> None:
        if future.cancelled():
            return
        try:
            result = future.result()
        except Exception:
            self.on_error()
            return
        self.on_complete(result)
