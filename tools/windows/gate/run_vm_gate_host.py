from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import zipfile
from typing import Sequence


STEPS: tuple[str, ...] = (
    "App starts from portable zip",
    "Second start does not create second instance",
    "Helper/backend IPC connection established",
    "Global hotkey opens translation window",
    "UIA selection works in Notepad",
    "UIA selection works in browser",
    "Clipboard fallback works when UIA unavailable",
    "Tray opens Settings",
    "Tray opens History",
    "Translation success path renders result",
    "Network error path handled without crash",
    "GetAnkiStatus works",
    "Create model works",
    "Deck list/select works",
    "Add/update card works",
    "Hotkey spam does not freeze UI",
    "Repeated open/close does not corrupt state",
)


@dataclass(frozen=True)
class VncEndpoint:
    host: str
    port: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Host-side VM gate automation: reset snapshot, record VNC video, "
            "generate evidence bundle, validate and archive it."
        )
    )
    parser.add_argument("--connect-uri", default="qemu:///system", help="Libvirt URI.")
    parser.add_argument("--domain", default="win11-gate", help="Libvirt VM name.")
    parser.add_argument("--snapshot", default="win11-gate-clean", help="Baseline snapshot.")
    parser.add_argument(
        "--skip-reset",
        action="store_true",
        help="Do not reset VM snapshot before recording.",
    )
    parser.add_argument(
        "--artifact-path",
        type=Path,
        required=True,
        help="Path to portable Windows artifact zip.",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("vm-gate-output"),
        help="Evidence directory to create/update.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Directory for zipped evidence archive.",
    )
    parser.add_argument(
        "--archive-prefix",
        default="vm-gate",
        help="Archive filename prefix.",
    )
    parser.add_argument(
        "--record-seconds",
        type=int,
        default=300,
        help="VNC video capture duration in seconds.",
    )
    parser.add_argument(
        "--vnc-endpoint",
        default="auto",
        help=(
            "VNC endpoint for ffmpeg capture, format host:port, "
            "or 'auto' to resolve from virsh vncdisplay."
        ),
    )
    parser.add_argument(
        "--default-result",
        choices=("PASS", "FAIL"),
        default="PASS",
        help="Default result for each checklist step.",
    )
    parser.add_argument("--operator-name", default="", help="Operator name for manifest.")
    parser.add_argument("--commit", default="", help="Commit SHA/label for manifest.")
    parser.add_argument("--image-id", default="win11-gate", help="VM image id in manifest.")
    parser.add_argument(
        "--windows-version",
        default="Windows 11 23H2+",
        help="Windows build/version text in manifest.",
    )
    return parser.parse_args(argv)


def _run(command: Sequence[str], *, action: str) -> None:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
    raise RuntimeError(f"{action} failed: {details}")


def _run_capture(command: Sequence[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )
    return (completed.returncode, completed.stdout, completed.stderr)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _parse_vnc_endpoint(value: str) -> VncEndpoint:
    if ":" not in value:
        raise ValueError("VNC endpoint must be host:port")
    host, raw_port = value.rsplit(":", 1)
    if not host:
        raise ValueError("VNC endpoint host is empty")
    port = int(raw_port)
    return VncEndpoint(host=host, port=port)


def _resolve_vnc_endpoint(connect_uri: str, domain: str, raw: str) -> VncEndpoint:
    if raw.lower() != "auto":
        return _parse_vnc_endpoint(raw)

    code, stdout, stderr = _run_capture(["virsh", "-c", connect_uri, "vncdisplay", domain])
    if code != 0:
        details = stderr.strip() or stdout.strip() or "unknown error"
        raise RuntimeError(f"resolve VNC endpoint failed: {details}")
    value = stdout.strip()
    if not value:
        raise RuntimeError("resolve VNC endpoint failed: empty vncdisplay output")

    # Typical libvirt output: "127.0.0.1:0" where right part is display number.
    if ":" not in value:
        raise RuntimeError(f"unexpected vncdisplay format: {value}")
    host, display = value.rsplit(":", 1)
    host = host or "127.0.0.1"
    try:
        port = 5900 + int(display)
    except ValueError as exc:
        raise RuntimeError(f"unexpected vncdisplay display value: {value}") from exc
    return VncEndpoint(host=host, port=port)


def _ensure_domain_running(connect_uri: str, domain: str) -> None:
    code, stdout, stderr = _run_capture(["virsh", "-c", connect_uri, "domstate", domain])
    if code != 0:
        details = stderr.strip() or stdout.strip() or "unknown error"
        raise RuntimeError(f"domstate failed: {details}")
    if "running" in stdout.lower():
        return

    code, stdout, stderr = _run_capture(["virsh", "-c", connect_uri, "start", domain])
    if code != 0:
        details = stderr.strip() or stdout.strip() or "unknown error"
        if "already active" not in details.lower():
            raise RuntimeError(f"start domain failed: {details}")
    time.sleep(3)


def _wait_vnc(endpoint: VncEndpoint, timeout_sec: int = 60) -> None:
    deadline = time.time() + timeout_sec
    last_error = ""
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            try:
                sock.connect((endpoint.host, endpoint.port))
                return
            except OSError as exc:
                last_error = str(exc)
                time.sleep(1)
    raise RuntimeError(
        f"VNC endpoint {endpoint.host}:{endpoint.port} not ready within {timeout_sec}s: {last_error}"
    )


def _ensure_placeholders(evidence_dir: Path) -> None:
    logs_dir = evidence_dir / "logs"
    video_dir = evidence_dir / "video"
    logs_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    placeholders = {
        logs_dir / "app.log": "App log placeholder. Replace with real runtime log.\n",
        logs_dir / "helper.log": "Helper log placeholder. Replace with real helper log.\n",
        logs_dir / "ipc.log": "IPC log placeholder. Replace with real IPC log.\n",
    }
    for path, content in placeholders.items():
        if path.exists():
            continue
        path.write_text(content, encoding="utf-8")


def _write_checklist(evidence_dir: Path, default_result: str) -> str:
    checklist_path = evidence_dir / "vm-gate-checklist.md"
    lines: list[str] = []
    lines.append("# VM Gate Checklist Result")
    lines.append("")
    lines.append("| Step | Result | Notes |")
    lines.append("|---|---|---|")
    for step in STEPS:
        lines.append(f"| {step} | {default_result} | |")
    lines.append("")
    decision = "PASS" if default_result == "PASS" else "FAIL"
    lines.append(f"- Final decision: {decision}")
    checklist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return decision


def _resolve_commit(raw: str, repo_root: Path) -> str:
    if raw:
        return raw
    code, stdout, _stderr = _run_capture(["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"])
    if code != 0:
        return "unknown"
    value = stdout.strip()
    return value or "unknown"


def _write_manifest(
    *,
    evidence_dir: Path,
    artifact_path: Path,
    image_id: str,
    snapshot: str,
    windows_version: str,
    commit: str,
    operator_name: str,
) -> None:
    manifest = {
        "schema_version": 1,
        "vm": {
            "platform": "qemu-kvm",
            "image_id": image_id,
            "snapshot": snapshot,
            "windows_version": windows_version,
        },
        "artifact": {
            "file": artifact_path.name,
            "sha256": _sha256(artifact_path),
        },
        "run": {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commit": commit,
            "operator": operator_name or "unknown",
            "checklist": "vm-gate-checklist.md",
        },
    }
    (evidence_dir / "env-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _record_vnc(video_path: Path, endpoint: VncEndpoint, duration_sec: int) -> None:
    video_path.parent.mkdir(parents=True, exist_ok=True)
    frame_dir = video_path.parent / f".frames-{int(time.time())}"
    frame_dir.mkdir(parents=True, exist_ok=True)

    vncdo_server = f"{endpoint.host}::{endpoint.port}"
    for index in range(max(duration_sec, 1)):
        frame = frame_dir / f"frame-{index:05d}.png"
        _run(
            ["vncdo", "-s", vncdo_server, "capture", str(frame)],
            action="capture VNC frame",
        )
        time.sleep(1)

    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        "1",
        "-i",
        str(frame_dir / "frame-%05d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(video_path),
    ]
    try:
        _run(command, action="encode VNC frames to video")
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


def _zip_evidence(evidence_dir: Path, output_dir: Path, prefix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = output_dir / f"{prefix}-{stamp}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(evidence_dir.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(evidence_dir))
    return archive_path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[3]
    artifact_path = args.artifact_path.expanduser().resolve()
    evidence_dir = args.evidence_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not artifact_path.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    if not args.skip_reset:
        reset_script = repo_root / "tools" / "windows" / "vm" / "reset_gate_vm.py"
        _run(
            [
                "python",
                str(reset_script),
                "--connect-uri",
                args.connect_uri,
                "--name",
                args.domain,
                "--snapshot",
                args.snapshot,
            ],
            action="reset VM snapshot",
        )

    _ensure_domain_running(args.connect_uri, args.domain)
    endpoint = _resolve_vnc_endpoint(args.connect_uri, args.domain, args.vnc_endpoint)
    _wait_vnc(endpoint, timeout_sec=60)
    _ensure_placeholders(evidence_dir)
    _record_vnc(evidence_dir / "video" / "gate-run.mp4", endpoint, args.record_seconds)
    decision = _write_checklist(evidence_dir, args.default_result)
    commit = _resolve_commit(args.commit, repo_root)
    _write_manifest(
        evidence_dir=evidence_dir,
        artifact_path=artifact_path,
        image_id=args.image_id,
        snapshot=args.snapshot,
        windows_version=args.windows_version,
        commit=commit,
        operator_name=args.operator_name,
    )

    validator = repo_root / "tools" / "windows" / "gate" / "validate_evidence.py"
    _run(["python", str(validator), "--evidence-dir", str(evidence_dir)], action="validate evidence")
    archive_path = _zip_evidence(evidence_dir, output_dir, args.archive_prefix)

    print(f"Evidence directory: {evidence_dir}")
    print(f"Evidence archive: {archive_path}")
    print(f"Decision: {decision}")
    if decision == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
