from __future__ import annotations

import argparse
import subprocess
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create baseline snapshot for Windows gate VM."
    )
    parser.add_argument("--name", default="win11-gate", help="Libvirt domain name.")
    parser.add_argument(
        "--snapshot",
        default="win11-gate-clean",
        help="Snapshot name to create.",
    )
    parser.add_argument(
        "--connect-uri",
        default="qemu:///system",
        help="Libvirt connection URI.",
    )
    parser.add_argument(
        "--description",
        default="Windows 11 gate baseline",
        help="Snapshot description.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=120,
        help="Timeout waiting for shutdown before snapshot.",
    )
    return parser.parse_args()


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def domain_state(connect_uri: str, name: str) -> str:
    completed = run_command(["virsh", "-c", connect_uri, "domstate", name])
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RuntimeError(f"failed to read domstate for '{name}': {details}")
    return completed.stdout.strip().lower()


def main() -> int:
    args = parse_args()
    state = domain_state(args.connect_uri, args.name)
    if "running" in state:
        shutdown = run_command(["virsh", "-c", args.connect_uri, "shutdown", args.name])
        if shutdown.returncode != 0:
            details = shutdown.stderr.strip() or shutdown.stdout.strip() or "unknown error"
            raise RuntimeError(f"failed to shutdown '{args.name}': {details}")

        deadline = time.time() + args.timeout_sec
        while time.time() < deadline:
            state = domain_state(args.connect_uri, args.name)
            if "shut off" in state:
                break
            time.sleep(2)
        else:
            raise RuntimeError(
                f"domain '{args.name}' did not stop within {args.timeout_sec} seconds"
            )

    snapshot = run_command(
        [
            "virsh",
            "-c",
            args.connect_uri,
            "snapshot-create-as",
            "--domain",
            args.name,
            "--name",
            args.snapshot,
            "--description",
            args.description,
            "--atomic",
        ]
    )
    if snapshot.returncode != 0:
        details = snapshot.stderr.strip() or snapshot.stdout.strip() or "unknown error"
        raise RuntimeError(f"snapshot creation failed: {details}")

    print(
        f"Snapshot '{args.snapshot}' created for '{args.name}' on {args.connect_uri}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
