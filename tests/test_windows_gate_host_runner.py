from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "windows" / "gate" / "run_vm_gate_host.py"
    spec = importlib.util.spec_from_file_location("run_vm_gate_host", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load run_vm_gate_host module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_vnc_endpoint() -> None:
    module = _module()
    endpoint = module._parse_vnc_endpoint("127.0.0.1:5900")
    assert endpoint.host == "127.0.0.1"
    assert endpoint.port == 5900

    try:
        module._parse_vnc_endpoint("bad-endpoint")
        raise AssertionError("Expected ValueError for endpoint without port")
    except ValueError:
        pass


def test_checklist_and_manifest_generation(tmp_path: Path) -> None:
    module = _module()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    artifact = tmp_path / "artifact.zip"
    artifact.write_bytes(b"artifact-bytes")

    module._ensure_placeholders(evidence)
    decision = module._write_checklist(evidence, "PASS")
    assert decision == "PASS"
    assert (evidence / "vm-gate-checklist.md").is_file()

    module._write_manifest(
        evidence_dir=evidence,
        artifact_path=artifact,
        image_id="win11-gate",
        snapshot="win11-gate-clean",
        windows_version="Windows 11 23H2+",
        commit="abc123",
        operator_name="tester",
    )
    manifest = json.loads((evidence / "env-manifest.json").read_text(encoding="utf-8"))
    assert manifest["run"]["commit"] == "abc123"
    assert manifest["run"]["operator"] == "tester"
    assert manifest["artifact"]["file"] == "artifact.zip"
    assert len(manifest["artifact"]["sha256"]) == 64
