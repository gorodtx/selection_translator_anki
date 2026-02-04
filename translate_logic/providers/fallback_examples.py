from __future__ import annotations

from typing import Final

from translate_logic.language_base.validation import normalize_spaces
from translate_logic.models import ExamplePair, ExampleSource

MIN_WORDS: Final[int] = 4


def build_fallback_examples(word: str, translation: str) -> tuple[ExamplePair, ...]:
    """Return 2 deterministic template examples.

    These are used only when we have no local language base yet.
    They are intentionally simple but always include the target word/phrase
    and the preferred Russian translation variant.
    """
    en1, ru1, en2, ru2 = _fallback_sentences(word, translation)
    return (
        ExamplePair(en=en1, ru=ru1, source=ExampleSource.TEMPLATE),
        ExamplePair(en=en2, ru=ru2, source=ExampleSource.TEMPLATE),
    )


def _fallback_sentences(word: str, translation: str) -> tuple[str, str, str, str]:
    normalized_word = normalize_spaces(word)
    normalized_translation = normalize_spaces(translation)
    if not normalized_word:
        return (
            "We talked about it at work today.",
            "Мы говорили об этом на работе сегодня.",
            "I wrote it down in my notes.",
            "Я записал это в свои заметки.",
        )
    if " " in normalized_word or "-" in normalized_word:
        return (
            f'I used "{normalized_word}" in a message today.',
            f'Я использовал "{normalized_translation}" в сообщении сегодня.',
            f'I heard "{normalized_word}" in a video yesterday.',
            f'Я услышал "{normalized_translation}" в видео вчера.',
        )
    return (
        f"We talked about the {normalized_word} at work today.",
        f"Мы говорили про {normalized_translation} на работе сегодня.",
        f"I wrote the {normalized_word} down in my notes.",
        f"Я записал {normalized_translation} в заметки.",
    )
