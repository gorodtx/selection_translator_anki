from __future__ import annotations

from translate_logic.providers.cambridge import CambridgeResult as CambridgeResult
from translate_logic.providers.cambridge import (
    translate_cambridge as translate_cambridge,
)
from translate_logic.providers.dictionary_api import (
    DictionaryApiResult as DictionaryApiResult,
    translate_dictionary_api as translate_dictionary_api,
)
from translate_logic.providers.google import GoogleResult as GoogleResult
from translate_logic.providers.google import translate_google as translate_google
from translate_logic.providers.tatoeba import TatoebaResult as TatoebaResult
from translate_logic.providers.tatoeba import translate_tatoeba as translate_tatoeba
