from __future__ import annotations

from translate_logic.providers.fallback_examples import (
    build_fallback_examples as build_fallback_examples,
)
from translate_logic.language_base.provider import (
    LanguageBaseProvider,
    default_language_base_path as default_language_base_path,
)
from translate_logic.providers.opus_mt import OpusMtProvider as OpusMtProvider

LanguageBaseExampleProvider = LanguageBaseProvider
