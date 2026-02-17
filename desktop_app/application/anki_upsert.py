from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnkiFieldAction(Enum):
    KEEP_EXISTING = "keep_existing"
    REPLACE_WITH_SELECTED = "replace_with_selected"
    MERGE_UNIQUE_SELECTED = "merge_unique_selected"


@dataclass(frozen=True, slots=True)
class AnkiUpsertValues:
    translations: tuple[str, ...]
    definitions_en: tuple[str, ...]
    examples_en: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnkiUpsertMatch:
    note_id: int
    word: str
    translation: str
    definitions_en: str
    examples_en: str


@dataclass(frozen=True, slots=True)
class AnkiUpsertPreview:
    values: AnkiUpsertValues
    matches: tuple[AnkiUpsertMatch, ...]
    available_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnkiUpsertDecision:
    create_new: bool
    target_note_ids: tuple[int, ...]
    translation_action: AnkiFieldAction
    definitions_action: AnkiFieldAction
    examples_action: AnkiFieldAction
    selected_translations: tuple[str, ...]
    selected_definitions_en: tuple[str, ...]
    selected_examples_en: tuple[str, ...]
