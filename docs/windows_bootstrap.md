# Windows Bootstrap Pack

This document is the honest Windows reproduction path for the current project state.

## Scope

- Exact runtime parity with the current Linux setup is not available on native Windows.
- The current runtime depends on GNOME Shell, GTK4 via `gi`, D-Bus, user `systemd`, `gsettings`, `gnome-extensions`, and Wayland/X11.
- Windows can still host the repo, Codex, tests, offline DBs, MCP tooling, and release automation.
- GNOME runtime validation still requires a Linux VM or a separate Linux machine.

Current source snapshot when this guide was written:

- branch: `gnome`
- commit: `d1296c1`
- Python target: `3.13`
- pinned DB bundle tag: `db-a6f07d1e1c28`

## Install On Windows

Install these before touching the repo:

- Git for Windows
- Python `3.13.x`
- Node.js `22.x`
- `uv`
- `ripgrep`
- Chrome or Chromium
- optional: SQLite CLI

Do not run Linux-only setup on Windows:

- `scripts/install.sh`
- `dev/tools/dev_setup.sh`
- `dev/tools/dev_reload.sh`

## Copy From The Source Machine

Copy these if you want the same Codex and app-level behavior:

- `%USERPROFILE%/.codex/skills`
- selected values from `%USERPROFILE%/.codex/config.toml`
- optional: `%USERPROFILE%/.config/translator/desktop_config.json`
- optional: repo `.env` if you use release automation and need `GITHUB_TOKEN`

After copying `%USERPROFILE%/.codex/skills`, verify these custom skills exist:

- `browser-use`
- `commit-title-from-diff`
- `decision-complete-planning`
- `find-skills`
- `full-reset-e2e-test-orchestrator`
- `mcp-fact-check-research`
- `purge-file-from-git-history`
- `quality-gates-smoke`
- `release-safe-rollback`
- `request-to-skill-builder`
- `source-trace-pipeline`
- `vps-sqlite-backup-pull`

System skills such as `.system/imagegen` and `.system/openai-docs` usually come with Codex and should only be verified, not copied manually.

Do not copy these as-is:

- `.venv`
- `.venv-desktop`
- `.pytest_cache`
- `.ruff_cache`
- `history.jsonl`
- `state_5.sqlite`
- `logs_*.sqlite`
- `sessions`
- `shell_snapshots`
- `app.lock`
- `app.pid`
- `last_selection.txt`
- raw tokens or passwords

## Exact Transfer Manifest

Copy or recreate these artifacts from the old machine:

- Linux `~/.codex/skills/` -> Windows `%USERPROFILE%/.codex/skills/`
- Linux `~/.config/translator/desktop_config.json` -> Windows `%USERPROFILE%/.config/translator/desktop_config.json`
- Linux repo `.env` -> Windows repo `.env` only if you need the same release automation setup

Do not copy this file raw:

- Linux `~/.codex/config.toml`

Instead, rebuild it on Windows from the tracked template:

- source template: `docs/windows_codex.config.example.toml`
- target path: `%USERPROFILE%/.codex/config.toml`

## Repo Bootstrap

Clone and pin the same branch and commit if you need a 1:1 source snapshot:

```powershell
git clone https://github.com/gorodtx/selection_translator_anki.git D:/dev/translator
Set-Location D:/dev/translator
git checkout gnome
git checkout d1296c1
```

Run the tracked bootstrap script from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -RepoRoot (Get-Location) -SetupVenv
```

What the script does:

- reports local tool availability and versions when present
- creates `.venv` with Python `3.13` when `-SetupVenv` is used
- runs `uv sync --group dev`
- downloads `primary.sqlite3`, `fallback.sqlite3`, and `definitions_pack.sqlite3`
- verifies their SHA-256 values against `scripts/db-bundle.lock.json`
- places DBs into `repo/offline_language_base`, which is already auto-discovered by the code

If you already created the venv and only want DB validation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -RepoRoot (Get-Location) -VerifyOnly
```

## Exact PowerShell Sequence

From a clean Windows shell:

```powershell
$Repo = "D:/dev/translator"
git clone https://github.com/gorodtx/selection_translator_anki.git $Repo
Set-Location $Repo
git checkout gnome
git checkout d1296c1

New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex" | Out-Null
Copy-Item ".\docs\windows_codex.config.example.toml" "$env:USERPROFILE\.codex\config.toml"

powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 `
  -RepoRoot $Repo `
  -SetupVenv `
  -CreateSkillsJunction
```

Then:

- edit `%USERPROFILE%/.codex/config.toml`
- copy `%USERPROFILE%/.codex/skills`
- re-auth connector-style MCP inside Codex
- optionally copy `%USERPROFILE%/.config/translator/desktop_config.json`

## Codex Config

Use the tracked template:

- `docs/windows_codex.config.example.toml`

Copy it to:

- `%USERPROFILE%/.codex/config.toml`

Then adjust:

- repo path
- filesystem MCP root
- email credentials
- any connector auth that is restored separately inside Codex

Notes:

- `fetch`, `sqlite`, and `mail` are pinned through `uvx`
- `chrome_devtools` and `puppeteer` should also be pinned if you want stricter reproducibility
- built-in or connector-style integrations such as GitHub, Figma, and OpenAI docs still need separate enablement or re-auth

## Chrome DevTools MCP

If you use browser MCP on Windows, start Chrome with remote debugging:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:USERPROFILE\.codex\chrome-devtools-profile"
```

## Optional App Config And Anki

The desktop config path is still built from `Path.home() / ".config"` in `desktop_app/config.py`.

On Windows that means:

- `%USERPROFILE%/.config/translator/desktop_config.json`

If you need Anki integration on Windows:

- install Windows Anki
- install AnkiConnect
- restore or recreate `desktop_config.json`

## What Works On Windows

- repo checkout and dependency sync
- offline DB placement in `offline_language_base`
- tests, lint, and type checks
- Codex project config, skills, and most MCP setup
- release tooling that does not depend on GNOME runtime
- optional AnkiConnect-based flows

Recommended validation:

```powershell
uv run pytest
uv run ruff check .
uv run pyright
```

## What Still Requires Linux

These remain Linux-only until the project gets a separate Windows frontend/runtime layer:

- GNOME Shell extension
- D-Bus service activation
- `systemctl --user`
- `gsettings`
- `gnome-extensions`
- Wayland/X11 selection and hotkey flow
- tray and popup runtime behavior

Use a Linux VM or separate Linux machine for:

- `dev/tools/dev_reload.sh`
- D-Bus smoke: `Translate "hello"`, `Translate "look up"`, `GetAnkiStatus`
- UI checks: open/close translation window, notification auto-hide, tray interactions
- hang/deadlock checks around hotkeys, tray, clipboard, and overlay
