# Parallel Runtime: Stable + Dev on one Linux GNOME machine

This workflow keeps your daily translator always stable while allowing isolated development on the same host.

## Stable contour (always-on)

- Install/update only from GitHub Releases via `scripts/install.sh` in `stable` mode.
- Never install from local checkout in stable contour.
- Runtime identifiers:
  - systemd: `translator-desktop.service`
  - D-Bus name: `com.translator.desktop`
  - extension UUID: `translator@com.translator.desktop`

## Dev contour (isolated)

- Work in separate git worktree (recommended path): `~/dev/translator-dev`.
- Run dev contour with `dev/run_dev_instance.sh`.
- Runtime identifiers (default):
  - systemd: `translator-desktop-dev.service`
  - D-Bus name: `com.translator.desktop.dev`
  - extension UUID: `translator-dev@com.translator.desktop`

## One-time setup (dev contour)

```bash
cd ~/dev/translator-dev
dev/run_dev_instance.sh setup
```

If `translator-dev@com.translator.desktop` is not visible right away in GNOME Extensions, log out and log in once (GNOME Shell reload).

Dev setup copies offline bases into the isolated dev runtime:
- `~/.local/share/translator-dev/current/app/translate_logic/infrastructure/language_base/offline_language_base/`
- files: `primary.sqlite3`, `fallback.sqlite3`, `definitions_pack.sqlite3`

## Daily commands (dev contour)

```bash
dev/run_dev_instance.sh status
dev/run_dev_instance.sh healthcheck
dev/run_dev_instance.sh reload
dev/run_dev_instance.sh stop
dev/run_dev_instance.sh start
```

## Switch active hotkey contour

```bash
# use dev extension + dev service for hotkey flow
dev/run_dev_instance.sh switch-to-dev

# return to stable extension + stable service
dev/run_dev_instance.sh switch-to-stable
```

## Tear down dev contour

```bash
dev/run_dev_instance.sh remove
```

## Safety checks

- Stable healthcheck:
  - `bash scripts/install.sh healthcheck`
- Dev healthcheck:
  - `dev/run_dev_instance.sh healthcheck`
- Verify no collisions:
  - stable D-Bus `com.translator.desktop`
  - dev D-Bus `com.translator.desktop.dev`
