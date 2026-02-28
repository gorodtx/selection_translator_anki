# Release Gate (Linux + Windows Independent Tracks)

This repository keeps Linux and Windows release tracks independent.

- Linux release quality is proven by Linux checks.
- Windows release quality is proven by Windows CI + mandatory Windows VM gate.
- Cross-substitution is not allowed.

## 1) Immutable release policy (mandatory)

- Versioning: `vMAJOR.MINOR.PATCH` (+ optional `-rc.N`).
- Existing tag/release assets are never replaced.
- Any fix after publish is a new `PATCH` tag.
- Channels:
  - `vX.Y.Z-rc.N`: cross-platform CI rehearsal.
  - `vX.Y.Z`: publish only after required gates are green for the target track.

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

## 3) Linux production gate (only for Linux release track)

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

## 4) Windows mandatory gate (for all Windows release work)

Windows gate source of truth:

1. Green Windows CI jobs in `.github/workflows/ci-matrix.yml`:
   - `windows-core-tests`
   - `windows-package-smoke`
   - `windows-ipc-smoke`
   - `windows-evidence-validate`
2. Mandatory VM gate on `QEMU/KVM` + `Windows 11 23H2+`.
3. Mandatory evidence bundle:
   - `vm-gate-checklist.md`
   - `env-manifest.json`
   - `logs/app.log`
   - `logs/helper.log`
   - `logs/ipc.log`
   - `video/gate-run.mp4`

Required docs and tools:

- `docs/windows/vm-gate.md`
- `docs/windows/vm-options-fact-check.md`
- `docs/windows/vm-gate-checklist.md`
- `docs/windows/env-manifest.schema.json`
- `tools/windows/gate/run_vm_gate.ps1`
- `tools/windows/gate/run_vm_gate_host.py`
- `tools/windows/gate/validate_evidence.py`
- `tools/windows/vm/preflight_host.py`
- `tools/windows/vm/provision_win11_vm.py`
- `tools/windows/vm/create_baseline_snapshot.py`
- `tools/windows/vm/reset_gate_vm.py`
- `tools/windows/vm/install_gate_prereqs_offline.py`

### Hard stop for Windows work in Linux host environment

During Windows implementation/validation, these are not valid acceptance checks:

- `dev/run_dev_instance.sh ...`
- `gdbus ...`
- Linux UI/runtime smoke

They must not be used as evidence for Windows readiness.

## 5) CI matrix gate

Single workflow: `.github/workflows/ci-matrix.yml`.

- `core-tests` (ubuntu/macos)
- `windows-core-tests`
- `windows-package-smoke`
- `windows-ipc-smoke`
- `windows-evidence-validate`
- `package-linux`
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
