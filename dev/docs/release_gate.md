# Stable Release Gate (Linux GNOME)

This project ships production artifacts for **Linux GNOME**.

## 1) Immutable release policy

- Versioning: `vMAJOR.MINOR.PATCH` (+ optional `-rc.N`).
- Existing tags/releases are never replaced.
- Any hotfix after publish is a new PATCH tag.

## 2) Preflight before publishing

```bash
dev/scripts/release_preflight.sh vX.Y.Z
```

What it enforces:
- clean tracked git tree,
- valid release tag format,
- tag does not exist locally/remotely,
- release assets built from tracked files only,
- checksums verified.

## 3) Stable Linux production gate

1. Restart runtime:
   - `systemctl --user restart translator-desktop.service`
2. Installer healthcheck:
   - `bash scripts/install.sh healthcheck`
3. Direct D-Bus smoke:
   - `gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.Translate "hello"`
   - `gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.Translate "look up"`
   - `gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.GetAnkiStatus`
4. Manual UI sanity:
   - hotkey opens/closes translation window,
   - tray menu opens History/Settings,
   - notification banner auto-hides (~1.2s).

## 4) Artifact cleanliness contract

- `translator-app.tar.gz` is built via `git archive` from explicit allowlist:
  - `desktop_app/`
  - `translate_logic/`
  - `icons/`
  - `scripts/runtime-requirements.txt`
- `.sqlite3` files are blocked inside app archive.
- Offline DB files ship only as separate release assets:
  - `primary.sqlite3`
  - `fallback.sqlite3`
  - `definitions_pack.sqlite3`

