from __future__ import annotations

from dataclasses import dataclass, field

from translate_logic.models import TranslationResult, TranslationStatus

WRAP_LIMIT = 85


@dataclass(frozen=True, slots=True)
class TranslationViewState:
    original: str
    translation: str
    example_en: str
    example_ru: str
    loading: bool
    can_add_anki: bool

    @classmethod
    def empty(cls) -> "TranslationViewState":
        return cls(
            original="",
            translation="",
            example_en="",
            example_ru="",
            loading=False,
            can_add_anki=False,
        )


@dataclass(slots=True)
class TranslationPresenter:
    _anki_available: bool = True
    _state: TranslationViewState = field(default_factory=TranslationViewState.empty)

    @property
    def state(self) -> TranslationViewState:
        return self._state

    def begin(self, original: str) -> TranslationViewState:
        self._state = TranslationViewState(
            original=_wrap_text(original),
            translation="",
            example_en="",
            example_ru="",
            loading=True,
            can_add_anki=False,
        )
        return self._state

    def clear(self) -> TranslationViewState:
        self._state = TranslationViewState.empty()
        return self._state

    def apply_partial(self, result: TranslationResult) -> TranslationViewState:
        translation = _wrap_text(result.translation_ru.text)
        self._state = TranslationViewState(
            original=self._state.original,
            translation=translation,
            example_en="",
            example_ru="",
            loading=True,
            can_add_anki=False,
        )
        return self._state

    def apply_final(self, result: TranslationResult) -> TranslationViewState:
        translation = _wrap_text(result.translation_ru.text)
        loading = False
        can_add = self._can_add(translation=translation, loading=loading)
        self._state = TranslationViewState(
            original=self._state.original,
            translation=translation,
            example_en=_wrap_text(result.example_en.text),
            example_ru=_wrap_text(result.example_ru.text),
            loading=loading,
            can_add_anki=can_add,
        )
        return self._state

    def mark_error(self) -> TranslationViewState:
        translation = self._state.translation
        loading = False
        self._state = TranslationViewState(
            original=self._state.original,
            translation=translation,
            example_en=self._state.example_en,
            example_ru=self._state.example_ru,
            loading=loading,
            can_add_anki=self._can_add(translation=translation, loading=loading),
        )
        return self._state

    def set_anki_available(self, available: bool) -> TranslationViewState:
        self._anki_available = available
        translation = self._state.translation
        self._state = TranslationViewState(
            original=self._state.original,
            translation=translation,
            example_en=self._state.example_en,
            example_ru=self._state.example_ru,
            loading=self._state.loading,
            can_add_anki=self._can_add(
                translation=translation, loading=self._state.loading
            ),
        )
        return self._state

    def reset_original(self, original: str) -> TranslationViewState:
        self._state = TranslationViewState(
            original=_wrap_text(original),
            translation=self._state.translation,
            example_en=self._state.example_en,
            example_ru=self._state.example_ru,
            loading=self._state.loading,
            can_add_anki=self._state.can_add_anki,
        )
        return self._state

    def is_success(self, result: TranslationResult) -> bool:
        return result.status is TranslationStatus.SUCCESS

    def _can_add(self, *, translation: str, loading: bool) -> bool:
        if loading:
            return False
        if not translation.strip():
            return False
        return self._anki_available


def _wrap_text(value: str) -> str:
    if not value:
        return ""
    lines: list[str] = []
    for chunk in value.splitlines():
        if not chunk:
            lines.append("")
            continue
        remaining = chunk
        while len(remaining) > WRAP_LIMIT:
            lines.append(remaining[:WRAP_LIMIT])
            remaining = remaining[WRAP_LIMIT:]
        lines.append(remaining)
    return "\n".join(lines)
