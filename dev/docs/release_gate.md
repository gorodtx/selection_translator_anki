# Release Gate (Linux production + Windows prep)

This project is production-supported on **Linux GNOME**.
Windows is in **prep mode** (architecture and validation scaffolding only).
macOS is **out of scope** for the current release cycle.

## 1) Immutable release policy (mandatory)

- Versioning: `vMAJOR.MINOR.PATCH` (+ optional `-rc.N`).
- Existing tag/release assets are never replaced.
- Any fix after publish is a new `PATCH` tag.
- Channels:
  - `vX.Y.Z-rc.N`: cross-platform CI rehearsal.
  - `vX.Y.Z`: publish only after green matrix + Linux production gate.

## 2) Preflight before publishing

```bash
dev/scripts/release_preflight.sh vX.Y.Z
```

What it enforces:
- clean tracked git tree,
- tag format check,
- tag does not exist locally/remotely,
- release assets built from tracked files only,
- checksums verified.

## 3) Linux production gate (mandatory)

1. Restart runtime:
   - `systemctl --user restart translator-desktop.service`
2. Installer healthcheck:
   - `bash scripts/install.sh healthcheck`
3. Direct health probes:
   - `gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.Translate "hello"`
   - `gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.Translate "look up"`
   - `gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.GetAnkiStatus`
4. Manual UI sanity:
   - hotkey opens/closes translation window,
   - tray menu opens History/Settings,
   - notification banner auto-hides (~1.2s).

## 4) Windows prep gate (non-blocking for Linux release)

Document results from Windows VM smoke:
- backend starts,
- no import/runtime crashes in core path,
- platform adapter contract remains Linux-isolated.

No production installer commitment for Windows in this phase.

## 5) CI matrix gate

Single workflow: `.github/workflows/ci-matrix.yml`.

- `core-tests` (matrix: ubuntu/windows/macos)
  - `fail-fast: false`
  - `max-parallel: 3`
- `package-linux`
- `package-windows`
- `package-macos`
- `sign-windows` (native step, secrets-gated)
- `notarize-macos` (native step, secrets-gated)

## 6) Stable vs dev contour rules

- Stable contour:
  - `TRANSLATOR_INSTALL_MODE=stable`
  - install/update/rollback only from release assets
  - local checkout install path must stay disabled
- Dev contour:
  - isolated worktree + `dev/run_dev_instance.sh`
  - separate D-Bus name / systemd unit / extension UUID

- bootstrap script: `dev/scripts/bootstrap_dev_worktree.sh`
- dev runtime launcher: `dev/run_dev_instance.sh`
