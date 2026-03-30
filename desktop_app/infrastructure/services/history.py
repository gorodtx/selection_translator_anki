from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from desktop_app.application.examples_state import EntryExamplesState
from desktop_app.application.history import HistoryItem
from translate_logic.models import TranslationResult

DEFAULT_HISTORY_MAX_ENTRIES: Final[int] = 100


def _default_items() -> list[HistoryItem]:
    return []


@dataclass(slots=True)
class HistoryStore:
    max_entries: int = DEFAULT_HISTORY_MAX_ENTRIES
    _items: list[HistoryItem] = field(default_factory=_default_items)
    _next_entry_id: int = 1

    def add(
        self,
        text: str,
        lookup_text: str,
        result: TranslationResult,
    ) -> HistoryItem:
        for index, item in enumerate(self._items):
            if item.text != text:
                continue
            updated = HistoryItem(
                entry_id=item.entry_id,
                text=item.text,
                lookup_text=lookup_text or item.lookup_text,
                result=result,
                examples_state=_merge_examples_state(
                    existing=item.examples_state,
                    lookup_text=lookup_text or item.lookup_text,
                    result=result,
                ),
            )
            self._items[index] = updated
            return updated
        created = HistoryItem(
            entry_id=self._next_entry_id,
            text=text,
            lookup_text=lookup_text,
            result=result,
            examples_state=EntryExamplesState.from_result(
                lookup_text=lookup_text,
                result=result,
            ),
        )
        self._next_entry_id += 1
        self._items.append(created)
        while len(self._items) > self.max_entries:
            self._items.pop(0)
        return created

    def get(self, entry_id: int) -> HistoryItem | None:
        for item in self._items:
            if item.entry_id == entry_id:
                return item
        return None

    def find_by_text(self, text: str) -> HistoryItem | None:
        for item in self._items:
            if item.text == text:
                return item
        return None

    def update_examples(
        self,
        entry_id: int,
        examples_state: EntryExamplesState,
    ) -> HistoryItem | None:
        for index, item in enumerate(self._items):
            if item.entry_id != entry_id:
                continue
            updated = HistoryItem(
                entry_id=item.entry_id,
                text=item.text,
                lookup_text=examples_state.lookup_text or item.lookup_text,
                result=item.result,
                examples_state=examples_state,
            )
            self._items[index] = updated
            return updated
        return None

    def snapshot(self) -> list[HistoryItem]:
        return list(reversed(self._items))


def _merge_examples_state(
    *,
    existing: EntryExamplesState,
    lookup_text: str,
    result: TranslationResult,
) -> EntryExamplesState:
    if existing.collected_examples:
        return EntryExamplesState(
            lookup_text=lookup_text.strip(),
            visible_examples=existing.visible_examples,
            collected_examples=existing.collected_examples,
            exhausted=existing.exhausted,
        )
    return EntryExamplesState.from_result(lookup_text=lookup_text, result=result)
