from __future__ import annotations

from translate_logic.language_base.validation import contains_word, matches_translation


def test_contains_word_matches_plural_and_ed_ing() -> None:
    assert contains_word("These tables are new.", "table")
    assert contains_word("He tabled the motion.", "table")
    assert contains_word("We are tabling this for now.", "table")
    assert contains_word("It's the table's leg.", "table")


def test_matches_translation_uses_ru_lemma() -> None:
    assert matches_translation("Ключи на столе.", "стол")
    assert matches_translation("Я подошёл к столу.", "стол")
    assert not matches_translation("Покажи мне таблицу.", "стол")
