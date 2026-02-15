from __future__ import annotations

from dataclasses import dataclass, field

from translate_logic.models import Example, TranslationResult, TranslationStatus

WRAP_LIMIT = 85


@dataclass(frozen=True, slots=True)
class ExampleViewItem:
    en: str


@dataclass(frozen=True, slots=True)
class TranslationViewState:
    original: str
    original_raw: str
    translation: str
    definitions_en: str
    definitions_items: tuple[str, ...]
    examples: tuple[ExampleViewItem, ...]
    loading: bool
    can_add_anki: bool

    @classmethod
    def empty(cls) -> "TranslationViewState":
        return cls(
            original="",
            original_raw="",
            translation="",
            definitions_en="",
            definitions_items=(),
            examples=(),
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
            original_raw=original,
            translation="",
            definitions_en="",
            definitions_items=(),
            examples=(),
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
            original_raw=self._state.original_raw,
            translation=translation,
            definitions_en="",
            definitions_items=(),
            examples=(),
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
            original_raw=self._state.original_raw,
            translation=translation,
            definitions_en=_format_definitions(result.definitions_en),
            definitions_items=tuple(result.definitions_en),
            examples=_format_examples(result),
            loading=loading,
            can_add_anki=can_add,
        )
        return self._state

    def mark_error(self) -> TranslationViewState:
        translation = self._state.translation
        loading = False
        self._state = TranslationViewState(
            original=self._state.original,
            original_raw=self._state.original_raw,
            translation=translation,
            definitions_en=self._state.definitions_en,
            definitions_items=self._state.definitions_items,
            examples=self._state.examples,
            loading=loading,
            can_add_anki=self._can_add(translation=translation, loading=loading),
        )
        return self._state

    def set_anki_available(self, available: bool) -> TranslationViewState:
        self._anki_available = available
        translation = self._state.translation
        self._state = TranslationViewState(
            original=self._state.original,
            original_raw=self._state.original_raw,
            translation=translation,
            definitions_en=self._state.definitions_en,
            definitions_items=self._state.definitions_items,
            examples=self._state.examples,
            loading=self._state.loading,
            can_add_anki=self._can_add(
                translation=translation, loading=self._state.loading
            ),
        )
        return self._state

    def reset_original(self, original: str) -> TranslationViewState:
        self._state = TranslationViewState(
            original=_wrap_text(original),
            original_raw=original,
            translation=self._state.translation,
            definitions_en=self._state.definitions_en,
            definitions_items=self._state.definitions_items,
            examples=self._state.examples,
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


def _format_definitions(definitions: tuple[str, ...]) -> str:
    if not definitions:
        return ""
    lines: list[str] = []
    for index, definition in enumerate(definitions, start=1):
        wrapped = _wrap_text(definition)
        if not wrapped:
            continue
        lines.append(f"{index}. {wrapped}")
    return "\n".join(lines)


def _format_examples(result: TranslationResult) -> tuple[ExampleViewItem, ...]:
    examples: list[Example] = list(result.examples)
    if not examples:
        return ()
    rows: list[ExampleViewItem] = []
    for example in examples[:3]:
        en = example.en
        if not en:
            continue
        rows.append(
            ExampleViewItem(
                en=en,
            )
        )
    return tuple(rows)
