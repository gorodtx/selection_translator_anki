from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _validator_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "windows" / "gate" / "validate_evidence.py"
    spec = importlib.util.spec_from_file_location("validate_evidence", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load validator module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_valid_evidence_dir(root: Path) -> Path:
    evidence_dir = root / "evidence"
    logs_dir = evidence_dir / "logs"
    video_dir = evidence_dir / "video"
    logs_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    (evidence_dir / "vm-gate-checklist.md").write_text(
        "# VM Gate Checklist Result\n\n- Final decision: PASS\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "vm": {
            "platform": "qemu-kvm",
            "image_id": "win11-gate",
            "snapshot": "win11-gate-clean",
            "windows_version": "Windows 11 23H2+",
        },
        "artifact": {
            "file": "translator-windows-preview.zip",
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        },
        "run": {
            "timestamp_utc": "2026-02-28T12:00:00Z",
            "commit": "1a2b3c4",
            "operator": "fixture",
            "checklist": "vm-gate-checklist.md",
        },
    }
    (evidence_dir / "env-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (logs_dir / "app.log").write_text("fixture app log\n", encoding="utf-8")
    (logs_dir / "helper.log").write_text("fixture helper log\n", encoding="utf-8")
    (logs_dir / "ipc.log").write_text("fixture ipc log\n", encoding="utf-8")
    (video_dir / "gate-run.mp4").write_bytes(b"fixture-video-bytes")
    return evidence_dir


def test_windows_evidence_dir_is_valid(tmp_path) -> None:
    module = _validator_module()
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "docs" / "windows" / "env-manifest.schema.json"
    evidence_dir = _build_valid_evidence_dir(tmp_path)

    exit_code = module.main(
        ["--evidence-dir", str(evidence_dir), "--schema", str(schema_path)]
    )

    assert exit_code == 0


def test_windows_evidence_validation_fails_when_required_file_missing(tmp_path) -> None:
    module = _validator_module()
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "docs" / "windows" / "env-manifest.schema.json"
    evidence_dir = _build_valid_evidence_dir(tmp_path)
    (evidence_dir / "video" / "gate-run.mp4").unlink()

    exit_code = module.main(
        ["--evidence-dir", str(evidence_dir), "--schema", str(schema_path)]
    )

    assert exit_code == 1
