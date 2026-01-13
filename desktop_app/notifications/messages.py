from __future__ import annotations

from desktop_app.notifications.models import Notification, NotificationLevel


def anki_success() -> Notification:
    return Notification("Card added to Anki.", NotificationLevel.SUCCESS)


def anki_duplicate() -> Notification:
    return Notification("Card already exists in Anki.", NotificationLevel.WARNING)


def anki_unavailable() -> Notification:
    return Notification("AnkiConnect is not available.", NotificationLevel.ERROR)


def anki_error(message: str) -> Notification:
    text = message.strip() or "Failed to add card to Anki."
    return Notification(text, NotificationLevel.ERROR)


def anki_model_exists(model_name: str) -> Notification:
    return Notification(
        f"Model already exists: {model_name}.",
        NotificationLevel.INFO,
    )


def anki_model_required(model_name: str) -> Notification:
    return Notification(
        f"Create Anki model: {model_name}.",
        NotificationLevel.WARNING,
    )


def anki_deck_selected(deck_name: str) -> Notification:
    return Notification(
        f"Deck selected: {deck_name}.",
        NotificationLevel.SUCCESS,
    )


def anki_deck_missing() -> Notification:
    return Notification(
        "Select an Anki deck in settings.",
        NotificationLevel.WARNING,
    )


def settings_saved() -> Notification:
    return Notification("Settings saved.", NotificationLevel.SUCCESS)


def copy_success() -> Notification:
    return Notification("Copied to clipboard.", NotificationLevel.SUCCESS)


def model_created(model_name: str) -> Notification:
    return Notification(
        f"Model created: {model_name}.",
        NotificationLevel.SUCCESS,
    )


def settings_error(message: str) -> Notification:
    text = message.strip() or "Settings error."
    return Notification(text, NotificationLevel.ERROR)


def translation_error() -> Notification:
    return Notification("Translation failed.", NotificationLevel.ERROR)
