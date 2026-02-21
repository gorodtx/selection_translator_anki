# Translator (GNOME)

![Translator](icons/main_icon.png)

**Stable:** GNOME build

A GNOME-first desktop translator that works on the **primary selection** and shows a minimal translation window. The GNOME Shell extension captures the hotkey, reads the selection, and forwards it to the Python backend over D-Bus.

## Highlights

- GNOME Shell hotkey (no busy cursor, no extra processes)
- Primary selection only (no clipboard writes)
- Two-stage UI update: fast partial → full
- Cambridge → Google ordering, strict deduplication
- Cache-aware repeat translations
- Clean GNOME integration via D-Bus activation

## Architecture

**Flow**
1) GNOME Shell Extension → reads PRIMARY selection
2) D-Bus call → Python backend (`com.translator.desktop`)
3) Translation pipeline → UI window + history

**Layers**
- **GNOME Extension (JS):** hotkey, selection read, D-Bus IPC
- **Backend (Python):** translation orchestration, caching, history, UI
- **Providers:** Cambridge / Google / DictionaryAPI / Tatoeba

## Tech stack

- GNOME Shell extension (GJS)
- D-Bus activation (session bus)
- GTK4 (Python GI)
- Python 3.13
- aiohttp (async HTTP)

## Installation (GNOME)

One command from Releases:

```bash
curl -fsSL https://github.com/igor3204/selection_translator_anki/releases/latest/download/install.sh | bash -s -- install
```

Local repository install/update/remove:

```bash
bash scripts/install.sh install
bash scripts/install.sh update
bash scripts/install.sh remove
```

Additional operations:

```bash
bash scripts/install.sh rollback
bash scripts/install.sh healthcheck
```

Notes:
- The installer is production-only: extension + backend runtime + user systemd + D-Bus + offline bases.
- Release assets are checksum-verified using `release-assets.sha256` and fail-fast on mismatch.
- Default release assets: `translator-app.tar.gz`, `translator-extension.zip`, `primary.sqlite3`, `fallback.sqlite3`, `definitions_pack.sqlite3`.
- Override release source with:
  - `TRANSLATOR_RELEASE_REPO=owner/repo`
  - `TRANSLATOR_RELEASE_TAG=vX.Y.Z`
  - `TRANSLATOR_ASSETS_BASE_URL=https://.../download`
  - `TRANSLATOR_ASSETS_MANIFEST_ASSET=release-assets.sha256`
  - `TRANSLATOR_ASSETS_MANIFEST_URL=https://.../release-assets.sha256`
  - `TRANSLATOR_ASSETS_MANIFEST_PATH=/path/to/release-assets.sha256`
  - `TRANSLATOR_APP_ASSET=translator-app.tar.gz`
  - `TRANSLATOR_EXTENSION_ASSET=translator-extension.zip`
- Release asset builder for maintainers: `dev/scripts/build_release_assets.sh`.
- Local developer reload scripts remain in `dev/tools/`.
- If the extension does not appear immediately, **log out and back in**.

## Usage

- Select text anywhere → press the hotkey
- Settings live in **GNOME Extensions** → Translator

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
