from __future__ import annotations

from pathlib import Path

from desktop_app.anki.importer import import_deck


def test_import_deck_missing_path(tmp_path: Path) -> None:
    result = import_deck(tmp_path / "missing.apkg")
    assert result.error is not None
    assert result.fields == []
