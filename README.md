# translator

CLI translation engine for selection_translator_anki.

Run:
`uv run python -m translator.cli "text"`

Output (4 lines only): `translation_ru`, `ipa_uk`, `example_en`, `example_ru`.

Behavior:
- Cambridge first (EN + EN-RU); Google Translate fallback if no usable RU.
- IPA/examples can be supplemented by DictionaryAPI/Tatoeba.
- Input keeps punctuation, collapses whitespace, max 200 chars; >5 words skip Cambridge.
- Async via aiohttp with an in-memory LRU+TTL cache; no audio.