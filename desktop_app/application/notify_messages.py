from __future__ import annotations

from desktop_app.application.notifications import NotificationMessage


def no_text() -> NotificationMessage:
    return NotificationMessage(title="Translator", body="No text selected.")


def no_english() -> NotificationMessage:
    return NotificationMessage(title="Translator", body="No English text selected.")


def unsupported_language() -> NotificationMessage:
    return NotificationMessage(title="Translator", body="Only EN -> RU is supported.")


def translation_failed() -> NotificationMessage:
    return NotificationMessage(title="Translator", body="Translation failed.")


def no_display() -> NotificationMessage:
    return NotificationMessage(title="Translator", body="No display available.")


def no_clipboard() -> NotificationMessage:
    return NotificationMessage(title="Translator", body="No clipboard available.")


def autostart_missing() -> NotificationMessage:
    return NotificationMessage(title="Translator", body="Autostart entry is missing.")


def hotkey_registered() -> NotificationMessage:
    return NotificationMessage(title="Hotkey", body="Hotkey applied.")


def hotkey_system_hint() -> NotificationMessage:
    return NotificationMessage(
        title="Hotkey", body="Set a system shortcut to run Translator."
    )


def ready_for_hotkey() -> NotificationMessage:
    return NotificationMessage(
        title="Translator", body="Select text and press the hotkey."
    )


def anki_config_required() -> NotificationMessage:
    return NotificationMessage(title="Anki", body="Configure deck/model/fields first.")


def anki_unavailable() -> NotificationMessage:
    return NotificationMessage(title="Anki", body="Anki is not available.")


def anki_duplicate() -> NotificationMessage:
    return NotificationMessage(title="Anki", body="Card already exists.")


def anki_failed() -> NotificationMessage:
    return NotificationMessage(title="Anki", body="Failed to add card.")


def anki_error(message: str) -> NotificationMessage:
    return NotificationMessage(title="Anki", body=message)


def settings_model_required() -> NotificationMessage:
    return NotificationMessage(
        title="Settings", body="Model name is required to fetch fields."
    )


def settings_deck_required() -> NotificationMessage:
    return NotificationMessage(title="Settings", body="Deck name is required.")


def settings_refresh_failed() -> NotificationMessage:
    return NotificationMessage(title="Settings", body="Failed to refresh Anki lists.")


def settings_fields_failed() -> NotificationMessage:
    return NotificationMessage(title="Settings", body="Failed to fetch model fields.")


def settings_schema_failed() -> NotificationMessage:
    return NotificationMessage(title="Settings", body="Failed to load deck schema.")


def settings_error(message: str) -> NotificationMessage:
    return NotificationMessage(title="Settings", body=message)


def settings_imported(deck: str, model: str) -> NotificationMessage:
    return NotificationMessage(
        title="Settings",
        body=f"Imported deck '{deck}' with model '{model}'.",
    )


def settings_deck_selected(deck: str) -> NotificationMessage:
    return NotificationMessage(
        title="Settings",
        body=f"Selected deck '{deck}'.",
    )


def settings_model_created(model: str) -> NotificationMessage:
    return NotificationMessage(
        title="Settings",
        body=f"Created Anki model '{model}'.",
    )


def settings_model_exists(model: str) -> NotificationMessage:
    return NotificationMessage(
        title="Settings",
        body=f"Anki model '{model}' already exists. Using it.",
    )
