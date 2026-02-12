from __future__ import annotations

from desktop_app.settings import missing_required_fields


def test_missing_required_fields_reports_all_missing() -> None:
    mapping = {
        "word": "",
        "translation": "",
        "example_en": "",
        "example_ru": "",
    }
    missing = missing_required_fields(mapping)
    assert missing == ["word", "translation", "example_en", "example_ru"]
