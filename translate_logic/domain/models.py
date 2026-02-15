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


class TranslationStatus(Enum):
    SUCCESS = "success"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class TranslationResult:
    translation_ru: FieldValue
    definitions_en: tuple[str, ...] = ()
    examples: tuple[Example, ...] = ()

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
