# Translator (GNOME)

![Translator](icons/main_icon.png)

**Stable:** GNOME build

A GNOME-first desktop translator that works on the **primary selection** and shows a minimal translation window. The GNOME Shell extension captures the hotkey, reads the selection, and forwards it to the Python backend over D-Bus.

## Highlights

- GNOME Shell hotkey (no busy cursor, no extra processes)
- Primary selection only (no clipboard writes)
- Two-stage UI update: fast partial → full
- Offline-first translation (local language base → OPUS-MT fallback)
- Cache-aware repeat translations
- Clean GNOME integration via D-Bus activation

## Architecture

**Flow**
1) GNOME Shell Extension → reads PRIMARY selection
2) D-Bus call → Python backend (`com.translator.desktop`)
3) Translation pipeline → UI window + history + Anki integration

**Layers**
- **GNOME Extension (JS):** hotkey, selection read, D-Bus IPC
- **Backend (Python):** translation orchestration, caching, history, UI
- **Translation engine:** local language base (SQLite FTS) + OPUS-MT (CTranslate2)

## Tech stack

- GNOME Shell extension (GJS)
- D-Bus activation (session bus)
- GTK4 (Python GI)
- Python 3.13
- CTranslate2 + SentencePiece (offline OPUS-MT)
- SQLite language base (optional but recommended)

## Installation (GNOME)

Download the install script from [Releases](https://github.com/igor3204/selection_translator_anki/releases) and run:

```bash
bash install_gnome.sh install
```

Update:

```bash
bash install_gnome.sh update
```

Remove:

```bash
bash install_gnome.sh remove
```

Notes:
- The script installs the GNOME extension, the Python backend, and the D-Bus service.
- If the extension does not appear immediately, **log out and back in**.

## Usage

- Select text anywhere → press the hotkey
- Settings live in **GNOME Extensions** → Translator

## CLI (debug / headless)

Run:
`uv run python -m translator.cli "text"`

Output (default, human-readable):
- Variants (3–7 when available).
- Examples (EN/RU pairs) as a **shared pool per request** (not per RU variant).

Use `--format json` for structured output.

## Offline assets (important)

- Models (required for translation):
  - `offline_assets/ct2/opus_mt/en-ru/`
- Optional (recommended) language bases with examples (primary + fallback):
  - `offline_language_base/primary.sqlite3` (primary, target <= 1.8GB)
  - `offline_language_base/fallback.sqlite3` (fallback, small)

Offline assets are distributed as **GitHub Release assets** (git has a 100MB file
limit). Download everything (models + language bases) in one command:

```bash
uv run python scripts/download_language_bases.py
```

After the download finishes, the app works fully offline (no further network calls).

This repository is designed to work offline after a one-time download from Releases.

---

> [!Road map on 2026:]
>
> - [ ] Universal language selection without quality loss
> - [ ] Interactive image search from source text to enrich Anki
> - [ ] Native free LLM for all users to enrich Anki content
>
>
> Supported systems:
> - [ ] Windows
> - [ ] Mac
> - [ ] Linux
> 	- [x] *wayland*
> 	- [x] *gnome*
> 	- [ ] *arch*
> 	- [ ] *kde*
> 	- [ ] *ubuntu*
