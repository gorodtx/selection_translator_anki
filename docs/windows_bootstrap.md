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
