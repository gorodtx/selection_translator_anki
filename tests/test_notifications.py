from __future__ import annotations

from desktop_app.notifications import messages
from desktop_app.notifications.models import NotificationLevel


def test_model_required_mentions_model() -> None:
    note = messages.anki_model_required("TestModel")
    assert "TestModel" in note.message
    assert note.level is NotificationLevel.WARNING


def test_deck_selected_mentions_deck() -> None:
    note = messages.anki_deck_selected("Deck A")
    assert "Deck A" in note.message


def test_settings_error_fallback() -> None:
    note = messages.settings_error(" ")
    assert note.message == "Settings error."
