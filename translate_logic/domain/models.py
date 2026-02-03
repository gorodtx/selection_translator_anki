from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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


class ExampleSource(Enum):
    LEGACY = "legacy"
    REVERSO = "reverso"
    OPUS_MT = "opus_mt"
    MT0 = "mt0"
    FALLBACK = "fallback"


class VariantSource(Enum):
    LEGACY = "legacy"
    REVERSO = "reverso"
    OPUS_MT = "opus_mt"


@dataclass(frozen=True, slots=True)
class ExamplePair:
    en: str
    ru: str
    source: ExampleSource


@dataclass(frozen=True, slots=True)
class TranslationVariant:
    ru: str
    pos: str | None
    synonyms: tuple[str, ...]
    examples: tuple[ExamplePair, ...]
    source: VariantSource


@dataclass(frozen=True, slots=True)
class TranslationResult:
    variants: tuple[TranslationVariant, ...]
    translation_ru: FieldValue = field(init=False)
    example_en: FieldValue = field(init=False)
    example_ru: FieldValue = field(init=False)

    def __post_init__(self) -> None:
        translation: str | None = None
        example_en: str | None = None
        example_ru: str | None = None
        if self.variants:
            translation = self.variants[0].ru
            if self.variants[0].examples:
                example_en = self.variants[0].examples[0].en
                example_ru = self.variants[0].examples[0].ru
        object.__setattr__(
            self, "translation_ru", FieldValue.from_optional(translation)
        )
        object.__setattr__(self, "example_en", FieldValue.from_optional(example_en))
        object.__setattr__(self, "example_ru", FieldValue.from_optional(example_ru))

    @classmethod
    def empty(cls) -> "TranslationResult":
        return cls(variants=())

    @property
    def status(self) -> TranslationStatus:
        if self.translation_ru.is_present:
            return TranslationStatus.SUCCESS
        return TranslationStatus.EMPTY


class TranslationLimit(Enum):
    PRIMARY = 4


class QueryLimit(Enum):
    MAX_CHARS = 200
