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
