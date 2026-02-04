from __future__ import annotations

from pathlib import Path

from translator.language_base.builder import build_language_base


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_builder_applies_max_words_and_cyrillic_filters(tmp_path: Path) -> None:
    en_path = tmp_path / "corpus.en"
    ru_path = tmp_path / "corpus.ru"
    out_path = tmp_path / "lang.sqlite3"

    _write_lines(
        en_path,
        [
            "one two three four five six seven eight nine",  # 9 words, ok
            "one two three four five six seven eight nine ten",  # 10 words, skip
            "I saw the table in the room.",  # ok, but RU latin-only -> skip
        ],
    )
    _write_lines(
        ru_path,
        [
            "раз два три четыре пять шесть семь восемь девять",
            "раз два три четыре пять шесть семь восемь девять десять",
            "hello world",
        ],
    )

    stats = build_language_base(
        en_path=en_path,
        ru_path=ru_path,
        out_path=out_path,
        min_words=4,
        max_words=9,
        max_per_anchor=100,
        require_ru_cyrillic=True,
        commit_every=2,
    )

    assert stats.read_rows == 3
    assert stats.inserted_rows == 1
    assert stats.skipped_rows == 2


def test_builder_stops_by_max_db_bytes(tmp_path: Path) -> None:
    en_path = tmp_path / "corpus.en"
    ru_path = tmp_path / "corpus.ru"
    out_path = tmp_path / "lang.sqlite3"

    n = 50_000
    _write_lines(en_path, [f"I saw the table in the room {i}." for i in range(n)])
    _write_lines(ru_path, [f"Я видел стол в комнате {i}." for i in range(n)])

    max_db_bytes = 200_000
    stats = build_language_base(
        en_path=en_path,
        ru_path=ru_path,
        out_path=out_path,
        min_words=4,
        max_words=9,
        max_per_anchor=10_000_000,
        require_ru_cyrillic=True,
        ratio_min=0.5,
        ratio_max=2.5,
        max_db_bytes=max_db_bytes,
        safety_margin_bytes=50_000,
        commit_every=200,
    )

    assert stats.read_rows < n
    assert out_path.stat().st_size <= max_db_bytes
