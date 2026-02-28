# Windows VM Options Fact Check (as of 2026-02-27)

## Scope

This document compares all practical Windows gate options for this repository and
selects one implementation path that preserves backend-core logic and avoids Linux
runtime acceptance artifacts.

## Constraints We Must Keep

- Mandatory release gate platform: `QEMU/KVM`.
- Mandatory guest baseline: `Windows 11 23H2+`.
- Required proof format: checklist + logs + video + env manifest.
- No changes to backend-core translation logic for VM rollout.
- Linux runtime checks are not accepted as Windows quality evidence.

## Fact-Checked Requirements

1. Windows 11 baseline requirements include Secure Boot capability, TPM 2.0,
   4 GB memory, and 64 GB storage.
2. Windows 11 lifecycle note:
   - Home/Pro 23H2 end of servicing: **2025-11-11**.
   - Enterprise/Education 23H2 end of servicing: **2026-11-10**.
3. libvirt domain XML supports TPM devices and firmware configuration controls,
   including secure-boot related firmware features.
4. `virt-install` supports TPM emulator options and UEFI firmware selection,
   which are required for reproducible Windows 11 setup.
5. VirtualBox also supports TPM config, but this project baseline is QEMU/KVM.

## Local Host Fact Check Snapshot (Machine-Specific)

Collected on Linux host at 2026-02-27:

- Hardware virtualization: present (`AMD-V`, `kvm`, `kvm_amd`, `/dev/kvm` accessible).
- QEMU/libvirt base: installed (`qemu-system-x86_64`, `virsh`, `qemu-img`).
- Current blockers for gate-ready state:
  - `virt-install` missing.
  - `swtpm` missing.
  - `qemu:///system` libvirt socket unavailable (`virtqemud-sock` not active).
  - User not in `kvm`/`libvirt` groups.
  - No swap configured (risk of host memory pressure during VM runs).
- Result: host is virtualization-capable but **not yet gate-ready** until blockers are fixed.

## Option Matrix

| Option | Technical Fit | Automation Fit | Risk | Result |
|---|---|---|---|---|
| QEMU/KVM + libvirt system + swtpm + OVMF | Full fit (TPM+UEFI+network+snapshots) | High (CLI + CI friendly) | Medium setup complexity | **Selected** |
| QEMU/KVM raw CLI only (no libvirt) | Can work | Medium | Higher maintenance, weaker team reproducibility | Not selected |
| VirtualBox | Works with TPM config | Medium | Diverges from mandatory hypervisor baseline | Not selected |
| VMware Workstation | Can host Win11 | Medium | Licensing + less aligned with gate standard | Not selected |
| Cloud Windows VM only | Useful as backup | Medium | Not native-on-this-machine requirement | Not selected |

## Selected Variant

`QEMU/KVM + libvirt (qemu:///system) + swtpm + OVMF secure boot + virt-install`

Why:
- Matches mandatory gate contract exactly.
- Best scriptability and evidence reproducibility.
- Lowest product risk for future blocking gate automation.

## Implemented Automation in This Repository

- `tools/windows/vm/preflight_host.py`
  - Runs deep host readiness checks:
    - KVM hardware/device/modules
    - required binaries (`qemu`, `virsh`, `virt-install`, `swtpm`, etc.)
    - OVMF secure boot firmware detection
    - libvirt connection/network/domcapabilities
    - TPM emulator availability in domcapabilities
    - RAM/disk/swap headroom
    - ISO path checks
- `tools/windows/vm/provision_win11_vm.py`
  - Creates/validates disk and runs `virt-install` with TPM emulator, q35, and UEFI.
- `tools/windows/vm/create_baseline_snapshot.py`
  - Ensures clean stop then creates `win11-gate-clean` snapshot.
- `tools/windows/vm/reset_gate_vm.py`
  - Reverts to baseline snapshot and starts VM for a fresh gate run.

## Acceptance Path (No Backend-Core Changes)

1. Run host readiness:

```bash
python tools/windows/vm/preflight_host.py --connect-uri qemu:///system
```

2. Provision VM once:

```bash
python tools/windows/vm/provision_win11_vm.py \
  --connect-uri qemu:///system \
  --windows-iso /absolute/path/Win11_23H2.iso \
  --virtio-iso /absolute/path/virtio-win.iso
```

3. After first clean guest setup, create baseline snapshot:

```bash
python tools/windows/vm/create_baseline_snapshot.py --connect-uri qemu:///system
```

4. Before each gate run:

```bash
python tools/windows/vm/reset_gate_vm.py --connect-uri qemu:///system
```

5. In guest VM, run gate evidence flow:
- `tools/windows/gate/run_vm_gate.ps1`
- `tools/windows/gate/collect_evidence.ps1`
- `tools/windows/gate/validate_evidence.py`

## Sources

- Microsoft Windows 11 requirements:
  - https://support.microsoft.com/en-us/windows/windows-11-system-requirements-86c11283-ea52-4782-9efd-7674389a7ba3
- Windows 11 release health / lifecycle:
  - https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information
- Windows 11 ISO download:
  - https://www.microsoft.com/software-download/windows11
- libvirt domain format (firmware/TPM):
  - https://libvirt.org/formatdomain.html
- `virt-install` manual:
  - https://manpages.ubuntu.com/manpages/jammy/man1/virt-install.1.html
- QEMU system invocation docs:
  - https://www.qemu.org/docs/master/system/invocation.html
- VirtualBox VM manage options (`--tpm-type`):
  - https://docs.oracle.com/en/virtualization/virtualbox/6.0/user/vboxmanage-modifyvm.html
- VMware (platform support reference):
  - https://knowledge.broadcom.com/external/article/313886/windows-11-support-on-vsphere.html
