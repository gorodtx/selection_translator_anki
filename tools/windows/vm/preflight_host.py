from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import grp
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from typing import Literal
import xml.etree.ElementTree as ET

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(slots=True)
class CheckResult:
    check_id: str
    status: Status
    details: str
    remediation: str = ""


@dataclass(slots=True)
class DomCapabilities:
    secure_loader_supported: bool
    tpm_supported: bool
    tpm_models: tuple[str, ...]
    tpm_backends: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preflight checks for Windows 11 VM gate on QEMU/KVM."
    )
    parser.add_argument(
        "--connect-uri",
        default="qemu:///system",
        help="Libvirt connection URI used for readiness checks.",
    )
    parser.add_argument(
        "--storage-path",
        type=Path,
        default=Path.home() / "vms" / "windows-gate",
        help="Target directory for Windows VM disks.",
    )
    parser.add_argument(
        "--windows-iso",
        type=Path,
        default=None,
        help="Optional path to Windows ISO for existence check.",
    )
    parser.add_argument(
        "--virtio-iso",
        type=Path,
        default=None,
        help="Optional path to VirtIO driver ISO for existence check.",
    )
    parser.add_argument(
        "--min-total-ram-gib",
        type=float,
        default=12.0,
        help="Fail if total RAM is below this value.",
    )
    parser.add_argument(
        "--recommended-total-ram-gib",
        type=float,
        default=16.0,
        help="Warn if total RAM is below this value.",
    )
    parser.add_argument(
        "--min-free-disk-gib",
        type=float,
        default=140.0,
        help="Fail if free disk in storage path is below this value.",
    )
    parser.add_argument(
        "--strict-warn",
        action="store_true",
        help="Treat warnings as failures (non-zero exit code).",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="Optional path to write structured JSON report.",
    )
    return parser.parse_args()


def run_command(command: list[str], timeout_sec: int = 15) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (127, "", str(exc))
    return (completed.returncode, completed.stdout, completed.stderr)


def command_exists(binary: str) -> bool:
    return shutil.which(binary) is not None


def parse_meminfo_kib(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value_match = re.search(r"(\d+)", raw_value)
        if value_match is None:
            continue
        result[key.strip()] = int(value_match.group(1))
    return result


def parse_lscpu_virtualization(text: str) -> tuple[bool, str]:
    virtualization = ""
    flags: set[str] = set()
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key == "virtualization":
            virtualization = normalized_value
        if normalized_key == "flags":
            flags = set(normalized_value.split())
    has_hw = bool(virtualization) or ("svm" in flags or "vmx" in flags)
    details = (
        "Virtualization="
        f"{virtualization or 'unknown'}, flags include svm/vmx={('svm' in flags) or ('vmx' in flags)}"
    )
    return (has_hw, details)


def select_ovmf_pair(candidate_dirs: list[Path]) -> tuple[Path | None, Path | None]:
    code_candidates: list[Path] = []
    vars_candidates: list[Path] = []
    for directory in candidate_dirs:
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            name = entry.name.lower()
            if "ovmf" not in name:
                continue
            if "code" in name and "secboot" in name:
                code_candidates.append(entry)
            if "vars" in name:
                vars_candidates.append(entry)
    code_candidates.sort()
    vars_candidates.sort()
    code = code_candidates[0] if code_candidates else None
    vars_file = vars_candidates[0] if vars_candidates else None
    return (code, vars_file)


def parse_domcapabilities(xml_text: str) -> DomCapabilities:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return DomCapabilities(False, False, (), ())

    secure_loader_supported = False
    tpm_supported = False
    tpm_models: list[str] = []
    tpm_backends: list[str] = []

    for loader in root.findall("./os/loader"):
        for enum_node in loader.findall("./enum"):
            if enum_node.attrib.get("name") != "secure":
                continue
            values = [value.text or "" for value in enum_node.findall("./value")]
            if "yes" in values:
                secure_loader_supported = True

    for tpm_node in root.findall("./devices/tpm"):
        if tpm_node.attrib.get("supported") == "yes":
            tpm_supported = True
        for enum_node in tpm_node.findall("./enum"):
            enum_name = enum_node.attrib.get("name")
            values = [value.text or "" for value in enum_node.findall("./value")]
            if enum_name == "model":
                tpm_models.extend(values)
            if enum_name == "backendModel":
                tpm_backends.extend(values)

    return DomCapabilities(
        secure_loader_supported=secure_loader_supported,
        tpm_supported=tpm_supported,
        tpm_models=tuple(sorted(set(tpm_models))),
        tpm_backends=tuple(sorted(set(tpm_backends))),
    )


def format_gib(kib_value: int) -> float:
    return kib_value / 1024.0 / 1024.0


def append_check(
    checks: list[CheckResult],
    check_id: str,
    status: Status,
    details: str,
    remediation: str = "",
) -> None:
    checks.append(
        CheckResult(
            check_id=check_id,
            status=status,
            details=details,
            remediation=remediation,
        )
    )


def run_preflight(args: argparse.Namespace) -> list[CheckResult]:
    checks: list[CheckResult] = []

    if platform.system().lower() != "linux":
        append_check(
            checks,
            "host.os",
            "FAIL",
            f"Unsupported host OS: {platform.system()}",
            "Use Linux host for QEMU/KVM gate.",
        )
        return checks

    append_check(
        checks,
        "host.os",
        "PASS",
        f"Host OS={platform.system()} {platform.release()} arch={platform.machine()}",
    )

    exit_code, lscpu_out, lscpu_err = run_command(["lscpu"])
    if exit_code != 0:
        append_check(
            checks,
            "host.cpu_virtualization",
            "FAIL",
            f"Failed to run lscpu: {lscpu_err or 'unknown error'}",
            "Install util-linux package and verify virtualization support in BIOS/UEFI.",
        )
    else:
        has_hw, details = parse_lscpu_virtualization(lscpu_out)
        append_check(
            checks,
            "host.cpu_virtualization",
            "PASS" if has_hw else "FAIL",
            details,
            "Enable AMD-V/Intel VT-x in BIOS/UEFI if missing.",
        )

    dev_kvm = Path("/dev/kvm")
    if not dev_kvm.exists():
        append_check(
            checks,
            "host.dev_kvm",
            "FAIL",
            "/dev/kvm is missing.",
            "Load kvm kernel modules and verify virtualization enabled in firmware.",
        )
    elif not os.access(dev_kvm, os.R_OK | os.W_OK):
        append_check(
            checks,
            "host.dev_kvm",
            "FAIL",
            "/dev/kvm exists but is not read/write for current user.",
            "Add user to kvm group or adjust udev permissions.",
        )
    else:
        append_check(checks, "host.dev_kvm", "PASS", "/dev/kvm is accessible.")

    exit_code, lsmod_out, _ = run_command(["lsmod"])
    if exit_code == 0 and re.search(r"^kvm(_amd|_intel)?\s", lsmod_out, flags=re.MULTILINE):
        append_check(checks, "host.kvm_modules", "PASS", "kvm modules are loaded.")
    else:
        append_check(
            checks,
            "host.kvm_modules",
            "FAIL",
            "kvm modules are not loaded.",
            "Load kvm and kvm_amd/kvm_intel kernel modules.",
        )

    required_binaries = (
        "qemu-system-x86_64",
        "qemu-img",
        "virsh",
        "virt-install",
        "virt-host-validate",
        "swtpm",
    )
    for binary in required_binaries:
        exists = command_exists(binary)
        append_check(
            checks,
            f"host.command.{binary}",
            "PASS" if exists else "FAIL",
            f"{binary} {'found' if exists else 'missing'}",
            "Install missing virtualization package(s).",
        )

    ovmf_dirs = [
        Path("/usr/share/edk2/x64"),
        Path("/usr/share/edk2-ovmf/x64"),
        Path("/usr/share/OVMF"),
    ]
    ovmf_code, ovmf_vars = select_ovmf_pair(ovmf_dirs)
    if ovmf_code is None or ovmf_vars is None:
        append_check(
            checks,
            "host.ovmf_secure_boot",
            "FAIL",
            "Failed to detect OVMF secure boot CODE/VARS firmware pair.",
            "Install OVMF/edk2-ovmf package with secure boot firmware files.",
        )
    else:
        append_check(
            checks,
            "host.ovmf_secure_boot",
            "PASS",
            f"CODE={ovmf_code} VARS={ovmf_vars}",
        )

    exit_code, validate_out, validate_err = run_command(["virt-host-validate", "qemu"])
    if exit_code != 0:
        append_check(
            checks,
            "host.virt_host_validate",
            "WARN",
            f"virt-host-validate exited with code {exit_code}: {validate_err or validate_out}",
            "Review warnings; continue only if critical checks are PASS.",
        )
    else:
        fail_count = len(re.findall(r":\s+FAIL", validate_out))
        warn_count = len(re.findall(r":\s+WARN", validate_out))
        if fail_count > 0:
            append_check(
                checks,
                "host.virt_host_validate",
                "FAIL",
                f"virt-host-validate reported FAIL entries: {fail_count}",
                "Resolve FAIL checks reported by virt-host-validate.",
            )
        elif warn_count > 0:
            append_check(
                checks,
                "host.virt_host_validate",
                "WARN",
                f"virt-host-validate warnings: {warn_count}",
                "Review warning list and document accepted warnings.",
            )
        else:
            append_check(
                checks,
                "host.virt_host_validate",
                "PASS",
                "virt-host-validate reported no WARN/FAIL entries.",
            )

    current_groups: set[str] = set()
    for group_id in os.getgroups():
        try:
            current_groups.add(grp.getgrgid(group_id).gr_name)
        except KeyError:
            continue
    missing_groups = [name for name in ("kvm", "libvirt") if name not in current_groups]
    if missing_groups:
        append_check(
            checks,
            "host.user_groups",
            "WARN",
            f"Missing groups: {', '.join(missing_groups)}",
            "Add user to kvm/libvirt groups and re-login for system libvirt workflow.",
        )
    else:
        append_check(checks, "host.user_groups", "PASS", "User has kvm/libvirt groups.")

    uri = args.connect_uri
    exit_code, _, uri_err = run_command(["virsh", "-c", uri, "uri"])
    if exit_code != 0:
        append_check(
            checks,
            "libvirt.connection",
            "FAIL",
            f"Cannot connect to {uri}: {uri_err.strip() or 'unknown error'}",
            "Start libvirt daemons/sockets and verify user permissions.",
        )
    else:
        append_check(checks, "libvirt.connection", "PASS", f"Connected to {uri}.")

        net_exit, net_out, net_err = run_command(
            ["virsh", "-c", uri, "net-info", "default"]
        )
        if net_exit != 0:
            append_check(
                checks,
                "libvirt.default_network",
                "WARN",
                f"default network unavailable: {net_err.strip() or net_out.strip()}",
                "Define/start libvirt default network or choose another network in provisioning.",
            )
        else:
            active_line = ""
            for line in net_out.splitlines():
                if line.strip().startswith("Active"):
                    active_line = line.strip()
                    break
            status: Status = "PASS" if "yes" in active_line.lower() else "WARN"
            remediation = "Start default network before VM creation." if status == "WARN" else ""
            append_check(
                checks,
                "libvirt.default_network",
                status,
                active_line or "default network info available",
                remediation,
            )

        dom_exit, dom_out, dom_err = run_command(
            [
                "virsh",
                "-c",
                uri,
                "domcapabilities",
                "--machine",
                "q35",
                "--arch",
                "x86_64",
                "--virttype",
                "kvm",
            ]
        )
        if dom_exit != 0:
            append_check(
                checks,
                "libvirt.domcapabilities",
                "FAIL",
                f"Failed to read domcapabilities: {dom_err.strip() or dom_out.strip()}",
                "Verify libvirt/qemu capabilities for q35+kvm.",
            )
        else:
            caps = parse_domcapabilities(dom_out)
            secure_ok = caps.secure_loader_supported
            tpm_ok = caps.tpm_supported and "emulator" in caps.tpm_backends

            append_check(
                checks,
                "libvirt.secure_boot",
                "PASS" if secure_ok else "FAIL",
                f"secure_loader_supported={caps.secure_loader_supported}",
                "Install/update OVMF firmware and libvirt that support secure boot.",
            )
            append_check(
                checks,
                "libvirt.tpm_emulator",
                "PASS" if tpm_ok else "FAIL",
                f"tpm_supported={caps.tpm_supported}, models={caps.tpm_models}, backends={caps.tpm_backends}",
                "Install swtpm and ensure libvirt exposes TPM backendModel=emulator.",
            )

    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.is_file():
        append_check(
            checks,
            "host.memory",
            "FAIL",
            "Cannot read /proc/meminfo",
            "Run on Linux host with /proc available.",
        )
    else:
        meminfo = parse_meminfo_kib(meminfo_path.read_text(encoding="utf-8"))
        total_kib = meminfo.get("MemTotal", 0)
        available_kib = meminfo.get("MemAvailable", 0)
        total_gib = format_gib(total_kib)
        available_gib = format_gib(available_kib)

        if total_gib < args.min_total_ram_gib:
            append_check(
                checks,
                "host.memory.total",
                "FAIL",
                f"Total RAM={total_gib:.1f} GiB < minimum {args.min_total_ram_gib:.1f} GiB",
                "Increase host RAM or reduce VM profile.",
            )
        elif total_gib < args.recommended_total_ram_gib:
            append_check(
                checks,
                "host.memory.total",
                "WARN",
                f"Total RAM={total_gib:.1f} GiB < recommended {args.recommended_total_ram_gib:.1f} GiB",
                "Use lower-concurrency host workload during VM gate runs.",
            )
        else:
            append_check(
                checks,
                "host.memory.total",
                "PASS",
                f"Total RAM={total_gib:.1f} GiB",
            )

        if available_gib < 8.0:
            append_check(
                checks,
                "host.memory.available",
                "WARN",
                f"MemAvailable={available_gib:.1f} GiB",
                "Close host workloads before running Windows VM gate.",
            )
        else:
            append_check(
                checks,
                "host.memory.available",
                "PASS",
                f"MemAvailable={available_gib:.1f} GiB",
            )

    storage_path: Path = args.storage_path.expanduser().resolve()
    storage_probe = storage_path if storage_path.exists() else storage_path.parent
    if not storage_probe.exists():
        append_check(
            checks,
            "host.disk",
            "FAIL",
            f"Storage path parent does not exist: {storage_probe}",
            "Create storage directory or adjust --storage-path.",
        )
    else:
        usage = shutil.disk_usage(storage_probe)
        free_gib = usage.free / (1024.0 ** 3)
        if free_gib < args.min_free_disk_gib:
            append_check(
                checks,
                "host.disk",
                "FAIL",
                f"Free disk={free_gib:.1f} GiB < minimum {args.min_free_disk_gib:.1f} GiB at {storage_probe}",
                "Free disk space or pick another storage location.",
            )
        else:
            append_check(
                checks,
                "host.disk",
                "PASS",
                f"Free disk={free_gib:.1f} GiB at {storage_probe}",
            )

    swap_total_kib = 0
    swap_path = Path("/proc/swaps")
    if swap_path.is_file():
        lines = swap_path.read_text(encoding="utf-8").splitlines()
        for line in lines[1:]:
            fields = line.split()
            if len(fields) >= 3:
                try:
                    swap_total_kib += int(fields[2])
                except ValueError:
                    continue
    if swap_total_kib == 0:
        append_check(
            checks,
            "host.swap",
            "WARN",
            "No swap detected.",
            "Configure swap to reduce host OOM risk during VM runs.",
        )
    else:
        append_check(
            checks,
            "host.swap",
            "PASS",
            f"Swap total={format_gib(swap_total_kib):.1f} GiB",
        )

    if args.windows_iso is not None:
        windows_iso = args.windows_iso.expanduser().resolve()
        exists = windows_iso.is_file()
        append_check(
            checks,
            "artifact.windows_iso",
            "PASS" if exists else "FAIL",
            f"Windows ISO {'found' if exists else 'missing'}: {windows_iso}",
            "Download Windows 11 ISO and pass correct path via --windows-iso.",
        )

    if args.virtio_iso is not None:
        virtio_iso = args.virtio_iso.expanduser().resolve()
        exists = virtio_iso.is_file()
        append_check(
            checks,
            "artifact.virtio_iso",
            "PASS" if exists else "WARN",
            f"VirtIO ISO {'found' if exists else 'missing'}: {virtio_iso}",
            "Provide VirtIO ISO to avoid missing network/storage drivers during install.",
        )

    return checks


def render_console_report(checks: list[CheckResult]) -> None:
    for check in checks:
        print(f"[{check.status}] {check.check_id}: {check.details}")
        if check.remediation:
            print(f"  remediation: {check.remediation}")

    pass_count = sum(1 for item in checks if item.status == "PASS")
    warn_count = sum(1 for item in checks if item.status == "WARN")
    fail_count = sum(1 for item in checks if item.status == "FAIL")
    print("")
    print(
        f"Summary: PASS={pass_count} WARN={warn_count} FAIL={fail_count} TOTAL={len(checks)}"
    )


def write_json_report(path: Path, checks: list[CheckResult]) -> None:
    payload = {
        "schema_version": 1,
        "checks": [asdict(check) for check in checks],
    }
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def exit_code_for(checks: list[CheckResult], strict_warn: bool) -> int:
    has_fail = any(check.status == "FAIL" for check in checks)
    has_warn = any(check.status == "WARN" for check in checks)
    if has_fail:
        return 1
    if strict_warn and has_warn:
        return 1
    return 0


def main() -> int:
    args = parse_args()
    checks = run_preflight(args)
    render_console_report(checks)

    if args.report_json is not None:
        write_json_report(args.report_json, checks)

    return exit_code_for(checks, strict_warn=args.strict_warn)


if __name__ == "__main__":
    sys.exit(main())
