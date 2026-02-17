from __future__ import annotations

from dataclasses import dataclass, field

from translate_logic.models import TranslationResult, TranslationStatus


@dataclass(slots=True)
class TranslationMemory:
    text: str = ""
    result: TranslationResult | None = None

    def reset(self) -> None:
        self.text = ""
        self.result = None

    def update(self, text: str, result: TranslationResult | None) -> None:
        self.text = text
        self.result = result

    def can_reuse(self, text: str, *, loading: bool) -> bool:
        if loading:
            return False
        normalized = text.strip()
        if not normalized:
            return False
        if normalized != self.text.strip():
            return False
        if self.result is None:
            return False
        if self.result.status is TranslationStatus.EMPTY:
            return False
        return True


@dataclass(slots=True)
class TranslationRequest:
    current_id: int = 0
    _presented: bool = False

    def next_id(self) -> int:
        self.current_id += 1
        self._presented = False
        return self.current_id

    def is_active(self, request_id: int) -> bool:
        return request_id == self.current_id

    def should_present(self, is_visible: bool) -> bool:
        del is_visible
        return not self._presented

    def mark_presented(self) -> None:
        self._presented = True


@dataclass(slots=True)
class TranslationState:
    memory: TranslationMemory = field(default_factory=TranslationMemory)
    request: TranslationRequest = field(default_factory=TranslationRequest)
