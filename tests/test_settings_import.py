from __future__ import annotations

from desktop_app.application import notify_messages
from desktop_app.settings import _missing_required_fields


def test_missing_required_fields_reports_all_missing() -> None:
    mapping = {
        "word": "",
        "ipa": "",
        "translation": "",
        "example_en": "",
        "example_ru": "",
    }
    missing = _missing_required_fields(mapping)
    assert missing == ["word", "ipa", "translation", "example_en", "example_ru"]


def test_settings_imported_message_includes_deck_and_model() -> None:
    message = notify_messages.settings_imported("Deck", "Model")
    assert "Deck" in message.body
    assert "Model" in message.body
