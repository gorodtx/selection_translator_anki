from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from translator.language_base.builder import build_fallback_language_base


def _write_zip(
    path: Path, *, prefix: str, en_lines: list[str], ru_lines: list[str]
) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{prefix}.en-ru.en", "\n".join(en_lines) + "\n")
        zf.writestr(f"{prefix}.en-ru.ru", "\n".join(ru_lines) + "\n")


def test_build_fallback_language_base_offline(tmp_path: Path) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    _write_zip(
        tmp_dir / "QED.en-ru.txt.zip",
        prefix="QED",
        en_lines=["Put the keys on the table.", "I need another one."],
        ru_lines=["Положи ключи на стол.", "Мне нужен еще один."],
    )
    _write_zip(
        tmp_dir / "Tatoeba.en-ru.txt.zip",
        prefix="Tatoeba",
        en_lines=["My mother is here.", "This table is old."],
        ru_lines=["Моя мама здесь.", "Этот стол старый."],
    )

    out_path = tmp_path / "fallback.sqlite3"
    stats = build_fallback_language_base(out_path=out_path, tmp_dir=tmp_dir)

    assert out_path.exists()
    assert stats.inserted_rows > 0

    conn = sqlite3.connect(out_path)
    try:
        corpora = conn.execute("SELECT value FROM meta WHERE key='corpora'").fetchone()
        assert corpora is not None
        assert corpora[0] == "QED,Tatoeba"
    finally:
        conn.close()
