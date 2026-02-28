from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Sequence


def _load_preflight_module():
    module_path = Path(__file__).with_name("preflight_host.py")
    spec = importlib.util.spec_from_file_location("preflight_host", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load preflight_host from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


preflight_host = _load_preflight_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision Windows 11 gate VM on QEMU/KVM via virt-install."
    )
    parser.add_argument("--name", default="win11-gate", help="Libvirt VM name.")
    parser.add_argument(
        "--connect-uri",
        default="qemu:///system",
        help="Libvirt URI used for VM creation.",
    )
    parser.add_argument(
        "--windows-iso",
        type=Path,
        required=True,
        help="Path to Windows 11 installation ISO.",
    )
    parser.add_argument(
        "--virtio-iso",
        type=Path,
        default=None,
        help="Optional path to VirtIO driver ISO.",
    )
    parser.add_argument(
        "--disk-path",
        type=Path,
        default=Path.home() / "vms" / "windows-gate" / "win11-gate.qcow2",
        help="Path to VM qcow2 disk.",
    )
    parser.add_argument(
        "--disk-size-gib",
        type=int,
        default=120,
        help="Disk size in GiB for new qcow2 image.",
    )
    parser.add_argument("--memory-mib", type=int, default=8192, help="VM memory.")
    parser.add_argument("--vcpus", type=int, default=4, help="VM vCPU count.")
    parser.add_argument(
        "--network",
        default="default",
        help="Libvirt network name (default: default).",
    )
    parser.add_argument(
        "--os-variant",
        default="win11",
        help="virt-install OS variant (example: win11).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing virt-install.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip preflight checks (not recommended).",
    )
    return parser.parse_args()


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )


def assert_command_ok(
    command: Sequence[str],
    *,
    error_hint: str,
) -> None:
    completed = run_command(command)
    if completed.returncode == 0:
        return
    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    details = stderr or stdout or "unknown error"
    raise RuntimeError(f"{error_hint}: {details}")


def vm_exists(connect_uri: str, name: str) -> bool:
    completed = run_command(["virsh", "-c", connect_uri, "dominfo", name])
    return completed.returncode == 0


def ensure_disk(path: Path, size_gib: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    assert_command_ok(
        ["qemu-img", "create", "-f", "qcow2", str(path), f"{size_gib}G"],
        error_hint="failed to create qcow2 disk",
    )


def resolve_ovmf_pair() -> tuple[Path, Path]:
    candidate_dirs = [
        Path("/usr/share/edk2/x64"),
        Path("/usr/share/edk2-ovmf/x64"),
        Path("/usr/share/OVMF"),
    ]
    code, vars_template = preflight_host.select_ovmf_pair(candidate_dirs)
    if code is None or vars_template is None:
        raise RuntimeError(
            "failed to detect OVMF secure-boot CODE/VARS pair. Install edk2-ovmf/OVMF."
        )
    return (code, vars_template)


def build_virt_install_command(
    *,
    connect_uri: str,
    name: str,
    memory_mib: int,
    vcpus: int,
    disk_path: Path,
    windows_iso: Path,
    virtio_iso: Path | None,
    network: str,
    os_variant: str,
    ovmf_code: Path,
    ovmf_vars: Path,
) -> list[str]:
    command = [
        "virt-install",
        "--connect",
        connect_uri,
        "--name",
        name,
        "--memory",
        str(memory_mib),
        "--vcpus",
        str(vcpus),
        "--cpu",
        "host-passthrough",
        "--machine",
        "q35",
        "--os-variant",
        os_variant,
        "--features",
        "smm=on",
        "--boot",
        (
            f"loader={ovmf_code},loader.readonly=yes,loader.type=pflash,"
            f"nvram.template={ovmf_vars}"
        ),
        "--disk",
        f"path={disk_path},format=qcow2,bus=virtio",
        "--cdrom",
        str(windows_iso),
        "--network",
        f"network={network},model=virtio",
        "--tpm",
        "backend.type=emulator,backend.version=2.0,model=tpm-crb",
        "--graphics",
        "spice",
        "--video",
        "virtio",
        "--noautoconsole",
    ]
    if virtio_iso is not None:
        command.extend(["--disk", f"path={virtio_iso},device=cdrom"])
    return command


def main() -> int:
    args = parse_args()
    windows_iso = args.windows_iso.expanduser().resolve()
    virtio_iso = args.virtio_iso.expanduser().resolve() if args.virtio_iso else None
    disk_path = args.disk_path.expanduser().resolve()

    if not windows_iso.is_file():
        print(f"Windows ISO not found: {windows_iso}", file=sys.stderr)
        return 1
    if virtio_iso is not None and not virtio_iso.is_file():
        print(f"VirtIO ISO not found: {virtio_iso}", file=sys.stderr)
        return 1

    if not args.skip_preflight:
        preflight_args = argparse.Namespace(
            connect_uri=args.connect_uri,
            storage_path=disk_path.parent,
            windows_iso=windows_iso,
            virtio_iso=virtio_iso,
            min_total_ram_gib=12.0,
            recommended_total_ram_gib=16.0,
            min_free_disk_gib=float(max(args.disk_size_gib + 20, 140)),
            strict_warn=False,
            report_json=None,
        )
        checks = preflight_host.run_preflight(preflight_args)
        preflight_host.render_console_report(checks)
        if preflight_host.exit_code_for(checks, strict_warn=False) != 0:
            print("Preflight reported failures. Aborting VM provisioning.", file=sys.stderr)
            return 1

    if vm_exists(args.connect_uri, args.name):
        print(
            f"Domain '{args.name}' already exists on {args.connect_uri}. "
            "Use a different --name or remove existing VM first.",
            file=sys.stderr,
        )
        return 1

    assert_command_ok(
        ["virsh", "-c", args.connect_uri, "net-info", args.network],
        error_hint=f"libvirt network '{args.network}' unavailable",
    )

    ensure_disk(disk_path, args.disk_size_gib)
    ovmf_code, ovmf_vars = resolve_ovmf_pair()
    command = build_virt_install_command(
        connect_uri=args.connect_uri,
        name=args.name,
        memory_mib=args.memory_mib,
        vcpus=args.vcpus,
        disk_path=disk_path,
        windows_iso=windows_iso,
        virtio_iso=virtio_iso,
        network=args.network,
        os_variant=args.os_variant,
        ovmf_code=ovmf_code,
        ovmf_vars=ovmf_vars,
    )

    printable_command = " ".join(shlex.quote(item) for item in command)
    print("virt-install command:")
    print(printable_command)

    if args.dry_run:
        print("Dry-run only. VM was not created.")
        return 0

    completed = run_command(command)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        print(f"virt-install failed: {details}", file=sys.stderr)
        return completed.returncode

    print("")
    print("VM provisioning completed.")
    print(f"Domain: {args.name}")
    print(f"Connect URI: {args.connect_uri}")
    print("Next steps:")
    print("1. Complete Windows installation in guest.")
    print("2. Install VirtIO drivers, Anki + AnkiConnect, and app dependencies.")
    print("3. Run create_baseline_snapshot.py after first clean setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
