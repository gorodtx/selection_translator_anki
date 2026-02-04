# translator

CLI translation engine for selection_translator_anki.

Run:
`uv run python -m translator.cli "text"`

Output (lines format):
- Variants (2–3 when available).
- Examples (EN/RU pairs) for each variant when present.
Use `--format json` for structured output.

Behavior:
- Offline-first pipeline.
- Translation variants come from the local language base when available, otherwise OPUS-MT.
- Examples come from the local language base (recommended: OPUS OpenSubtitles); templates are used only when the DB is missing.
- Input keeps punctuation, collapses whitespace, max 200 chars.

Offline assets (important):
- The directory `offline_assets/` contains everything required for fast offline translation.
- Models (required for translation):
  - `offline_assets/ct2/opus_mt/en-ru/`
- Optional (recommended) language base with examples:
  - `offline_language_base/language_base.sqlite3`

This repository is designed to work offline from a fresh clone:
- No model downloads.
- No fallback paths outside the repository checkout.
