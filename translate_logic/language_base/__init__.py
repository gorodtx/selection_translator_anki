"""Local language base (OPUS OpenSubtitles) support.

This package contains:
- SQLite FTS-backed provider for examples and translation variants.
- Validation / normalization utilities used during querying and DB building.

The language base is designed to be distributed with the repository for
fully-offline work.
"""

from __future__ import annotations

from translate_logic.language_base.provider import (
    LanguageBaseProvider as LanguageBaseProvider,
    default_fallback_language_base_path as default_fallback_language_base_path,
    default_language_base_path as default_language_base_path,
)
from translate_logic.language_base.multi_provider import (
    MultiLanguageBaseProvider as MultiLanguageBaseProvider,
)
from translate_logic.language_base.validation import (
    MIN_EXAMPLE_WORDS as MIN_EXAMPLE_WORDS,
    contains_word as contains_word,
    matches_translation as matches_translation,
    normalize_spaces as normalize_spaces,
    word_count as word_count,
)
