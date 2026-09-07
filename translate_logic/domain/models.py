from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class Example:
    en: str


class FieldStatus(Enum):
    MISSING = "missing"
    PRESENT = "present"


@dataclass(frozen=True, slots=True)
class FieldValue:
    text: str
    status: FieldStatus

    @classmethod
    def missing(cls) -> "FieldValue":
        return cls(text="", status=FieldStatus.MISSING)

    @classmethod
    def present(cls, text: str) -> "FieldValue":
        normalized = text.strip()
        if not normalized:
            return cls.missing()
        return cls(text=normalized, status=FieldStatus.PRESENT)

    @classmethod
    def from_optional(cls, value: str | None) -> "FieldValue":
        if value is None:
            return cls.missing()
        return cls.present(value)

    @property
    def is_present(self) -> bool:
        return self.status is FieldStatus.PRESENT


@dataclass(frozen=True, slots=True)
class SourceToggles:
    """Which translation sources the user allows.

    Lives in the domain because the pipeline honours them; the desktop config
    stores the same shape so a toggle in the UI reaches the engine unchanged.
    """

    apple_dictionary: bool = True
    apple_translation: bool = True
    google: bool = True
    cambridge: bool = True
    offline_examples: bool = True
    definitions_pack: bool = True

    @property
    def any_network(self) -> bool:
        return self.google or self.cambridge

    @property
    def any_apple(self) -> bool:
        return self.apple_dictionary or self.apple_translation


class TranslationStatus(Enum):
    SUCCESS = "success"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class ExamplePair:
    en: str
    ru: str


@dataclass(frozen=True, slots=True)
class LexicalSense:
    index: int
    label: str
    translation: str
    examples: tuple[ExamplePair, ...] = ()


@dataclass(frozen=True, slots=True)
class LexicalEntry:
    pos: str
    senses: tuple[LexicalSense, ...] = ()


@dataclass(frozen=True, slots=True)
class LexicalInfo:
    """Dictionary-grade data (IPA, parts of speech, numbered senses) that the
    plain translation string cannot carry; populated by on-device engines."""

    headword: str
    ipa_uk: str = ""
    ipa_us: str = ""
    entries: tuple[LexicalEntry, ...] = ()
    source: str = "apple_dictionary"


@dataclass(frozen=True, slots=True)
class TranslationResult:
    translation_ru: FieldValue
    definitions_en: tuple[str, ...] = ()
    examples: tuple[Example, ...] = ()
    lexical: LexicalInfo | None = None

    @classmethod
    def empty(cls) -> "TranslationResult":
        return cls(
            translation_ru=FieldValue.missing(),
            definitions_en=(),
            examples=(),
        )

    @property
    def status(self) -> TranslationStatus:
        if self.translation_ru.is_present:
            return TranslationStatus.SUCCESS
        return TranslationStatus.EMPTY


class TranslationLimit(Enum):
    PRIMARY = 8


class QueryLimit(Enum):
    MAX_CHARS = 200
    MAX_CAMBRIDGE_WORDS = 5


class ExampleLimit(Enum):
    MIN_WORDS = 2
