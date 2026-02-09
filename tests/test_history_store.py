from __future__ import annotations

from desktop_app.services.history import HistoryStore
from translate_logic.models import FieldValue, TranslationResult


def _result(text: str) -> TranslationResult:
    return TranslationResult(
        translation_ru=FieldValue.present(text),
        ipa_uk=FieldValue.missing(),
        example_en=FieldValue.missing(),
        example_ru=FieldValue.missing(),
    )


def test_history_store_removes_duplicates() -> None:
    store = HistoryStore()

    store.add("hello", _result("one"))
    store.add("world", _result("one"))
    store.add("hello", _result("two"))

    snapshot = store.snapshot()

    assert [item.text for item in snapshot] == ["world", "hello"]
    assert snapshot[1].result.translation_ru.text == "one"
