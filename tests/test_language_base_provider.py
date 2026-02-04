from __future__ import annotations

import sqlite3
from pathlib import Path

from translate_logic.language_base.provider import LanguageBaseProvider


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE examples_fts "
            "USING fts5(en, ru UNINDEXED, tokenize='unicode61')"
        )
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO examples_fts(en, ru) VALUES(?, ?)",
            (
                "The bride wore a beautiful dress.",
                "Невеста была в красивом платье.",
            ),
        )
        conn.execute(
            "INSERT INTO examples_fts(en, ru) VALUES(?, ?)",
            (
                "She bought a new dress yesterday.",
                "Вчера она купила новое платье.",
            ),
        )
        conn.execute(
            "INSERT INTO examples_fts(en, ru) VALUES(?, ?)",
            (
                "This is a dress.",
                "Это штука.",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_language_base_schema_is_compact(tmp_path: Path) -> None:
    db_path = tmp_path / "lang.sqlite3"
    _create_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='examples_fts'"
        ).fetchone()
        assert sql is not None
        assert "ru unindexed" in str(sql[0]).casefold()
        assert "source" not in str(sql[0]).casefold()
        meta = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        assert meta is not None
    finally:
        conn.close()


def test_language_base_provider_prefers_translation_match(tmp_path: Path) -> None:
    db_path = tmp_path / "lang.sqlite3"
    _create_db(db_path)

    provider = LanguageBaseProvider(db_path=db_path, fts_limit=50)
    examples = provider.get_examples(word="dress", translation="платье", limit=2)

    assert len(examples) == 2
    assert all("dress" in item.en.casefold() for item in examples)
    assert all("плать" in item.ru.casefold() for item in examples)
    assert provider.is_available


def test_language_base_provider_extracts_variants_from_ru_side(tmp_path: Path) -> None:
    db_path = tmp_path / "lang.sqlite3"
    _create_db(db_path)

    # Add extra "table" rows to make RU-side frequency meaningful.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO examples_fts(en, ru) VALUES(?, ?)",
            (
                "Put the keys on the table.",
                "Положи ключи на стол.",
            ),
        )
        conn.execute(
            "INSERT INTO examples_fts(en, ru) VALUES(?, ?)",
            (
                "The table is in the kitchen.",
                "Стол на кухне.",
            ),
        )
        conn.execute(
            "INSERT INTO examples_fts(en, ru) VALUES(?, ?)",
            (
                "The keys are on the table.",
                "Ключи на столе.",
            ),
        )
        conn.execute(
            "INSERT INTO examples_fts(en, ru) VALUES(?, ?)",
            (
                "Show me the table.",
                "Покажи мне таблицу.",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    provider = LanguageBaseProvider(db_path=db_path, fts_limit=50)
    variants = provider.get_variants(word="table", limit=3)

    assert variants
    assert "стол" in variants
