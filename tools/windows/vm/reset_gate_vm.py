from __future__ import annotations

import argparse
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Revert gate VM to baseline snapshot and start it."
    )
    parser.add_argument("--name", default="win11-gate", help="Libvirt domain name.")
    parser.add_argument(
        "--snapshot",
        default="win11-gate-clean",
        help="Snapshot name to revert.",
    )
    parser.add_argument(
        "--connect-uri",
        default="qemu:///system",
        help="Libvirt connection URI.",
    )
    return parser.parse_args()


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def assert_ok(command: list[str], *, action: str) -> None:
    completed = run_command(command)
    if completed.returncode == 0:
        return
    details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
    raise RuntimeError(f"{action} failed: {details}")


def main() -> int:
    args = parse_args()

    assert_ok(
        [
            "virsh",
            "-c",
            args.connect_uri,
            "snapshot-revert",
            "--domain",
            args.name,
            "--snapshotname",
            args.snapshot,
            "--running",
        ],
        action=f"snapshot revert {args.name}/{args.snapshot}",
    )

    # Start may fail if domain is already running after revert.
    start = run_command(["virsh", "-c", args.connect_uri, "start", args.name])
    if start.returncode != 0:
        details = start.stderr.strip() or start.stdout.strip() or "unknown error"
        if "already active" not in details.lower():
            raise RuntimeError(f"start domain failed: {details}")

    print(
        f"Domain '{args.name}' reverted to snapshot '{args.snapshot}' and started on {args.connect_uri}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
