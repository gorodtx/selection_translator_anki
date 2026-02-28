# Windows VM Gate (Mandatory)

This document defines the blocking quality gate for Windows release work.

## Hard Stop: Host Runtime

When implementing or validating Windows features in this repository:

- Do not run `dev/run_dev_instance.sh` actions.
- Do not call `systemctl --user` for `translator*`.
- Do not execute `gdbus` calls against `com.translator.desktop*`.
- Do not use Linux GNOME runtime checks as Windows acceptance evidence.

Windows acceptance is valid only through Windows CI + Windows VM gate.

## Target Baseline

- Hypervisor: `QEMU/KVM`
- Guest OS: `Windows 11 23H2+`
- App package under test: portable zip artifact
- Evidence format: checklist + logs + video + env manifest
- Libvirt profile: `qemu:///system`

Decision and fact-check details: `docs/windows/vm-options-fact-check.md`.

## One-Time Host Setup (Linux)

Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients virtinst ovmf swtpm
sudo usermod -aG libvirt,kvm "$USER"
```

Arch/Manjaro:

```bash
sudo pacman -S --needed qemu-desktop libvirt edk2-ovmf virt-install swtpm dnsmasq
sudo usermod -aG libvirt,kvm "$USER"
```

Or run the idempotent setup script (recommended):

```bash
sudo tools/windows/vm/setup_host_root.sh "$USER"
```

Enable libvirt sockets (or service, depending on distro defaults):

```bash
sudo systemctl enable --now virtqemud.socket
sudo systemctl enable --now virtnetworkd.socket
```

Re-login after group changes.

## Host Readiness Preflight (Mandatory)

Run before provisioning and before gate waves:

```bash
python tools/windows/vm/preflight_host.py \
  --connect-uri qemu:///system \
  --report-json dev/tmp/windows-vm-preflight.json
```

Use strict mode when preparing release gate hosts:

```bash
python tools/windows/vm/preflight_host.py \
  --connect-uri qemu:///system \
  --strict-warn
```

## Create VM (One-Time)

Use the provisioning tool:

```bash
python tools/windows/vm/provision_win11_vm.py \
  --connect-uri qemu:///system \
  --name win11-gate \
  --windows-iso /absolute/path/Win11_23H2.iso \
  --virtio-iso /absolute/path/virtio-win.iso \
  --disk-path "$HOME/vms/windows-gate/win11-gate.qcow2" \
  --disk-size-gib 120 \
  --memory-mib 8192 \
  --vcpus 4
```

Dry-run command preview:

```bash
python tools/windows/vm/provision_win11_vm.py \
  --connect-uri qemu:///system \
  --windows-iso /absolute/path/Win11_23H2.iso \
  --dry-run
```

After OS install in guest:
- apply Windows updates to 23H2+
- install VirtIO guest drivers
- install Anki + AnkiConnect
- install tooling required by your Windows app build

Optional host-driven offline prerequisite install from attached payload ISO (requires
focused admin `cmd.exe` session in guest):

```bash
python tools/windows/vm/install_gate_prereqs_offline.py \
  --connect-uri qemu:///system \
  --domain win11-gate \
  --open-cmd \
  --capture-dir "$HOME/vms/windows-gate"
```

Create clean baseline snapshot:

```bash
python tools/windows/vm/create_baseline_snapshot.py \
  --connect-uri qemu:///system \
  --name win11-gate \
  --snapshot win11-gate-clean
```

## Gate Run Protocol

1. Revert to baseline snapshot before every gate run:

```bash
python tools/windows/vm/reset_gate_vm.py \
  --connect-uri qemu:///system \
  --name win11-gate \
  --snapshot win11-gate-clean
```

2. Copy Windows artifact zip into VM.
3. Run VM gate flow in guest:
- `tools/windows/gate/run_vm_gate.ps1`
4. Validate evidence bundle:
- `tools/windows/gate/validate_evidence.py`

## Host-Side Automated Gate Runner

For a fully scripted host-side run (snapshot reset + VNC video + checklist/log placeholders
+ manifest + validation + zipped archive), use:

```bash
python tools/windows/gate/run_vm_gate_host.py \
  --connect-uri qemu:///system \
  --domain win11-gate \
  --snapshot win11-gate-clean \
  --artifact-path /absolute/path/translator-windows-portable.zip \
  --evidence-dir ./vm-gate-output \
  --output-dir ./dist \
  --record-seconds 300 \
  --vnc-endpoint 127.0.0.1:5900 \
  --default-result PASS
```

Note: this runner automates artifact creation and evidence packaging. Functional pass/fail
still depends on real gate execution quality and attached logs.

## Mandatory Functional Scenarios

1. Startup and single-instance behavior.
2. Named Pipe IPC: handshake + command/response path.
3. Global hotkey opens/closes translator window.
4. UIA selection in Notepad + browser.
5. Clipboard fallback when UIA is unavailable.
6. Tray opens Settings and History.
7. Translation success and error handling.
8. Anki required flow:
- status
- create model
- list/select deck
- add/update card
9. Stability:
- hotkey spam
- repeated translate
- repeated settings/history open-close
- no freeze/crash

## Required Evidence Bundle

Required files in evidence directory:

- `vm-gate-checklist.md`
- `env-manifest.json`
- `logs/app.log`
- `logs/helper.log`
- `logs/ipc.log`
- `video/gate-run.mp4`

Optional:

- `logs/crash-dumps/*`
- screenshots

## Pass/Fail Rules

- Any critical scenario fail => gate fail.
- Missing required evidence file => gate fail.
- Invalid manifest schema => gate fail.
- Known issue allowed only with:
  - linked issue
  - owner
  - ETA
  - explicit temporary waiver note in release notes

## Important Boundary

This gate validates Windows runtime behavior in VM and Windows CI only.
It does not require Linux runtime actions for acceptance of Windows work.
