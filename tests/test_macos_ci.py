from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "macos.yml"

type JobMap = dict[str, dict[str, Any]]
type Step = dict[str, Any]


def _workflow() -> dict[str, Any]:
    loaded: object = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _jobs() -> JobMap:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    return cast(JobMap, jobs)


def _steps(job: str) -> list[Step]:
    steps = _jobs()[job]["steps"]
    assert isinstance(steps, list)
    return cast(list[Step], steps)


def _commands(job: str) -> str:
    return " ".join(str(step.get("run", "")) for step in _steps(job))


def test_workflow_declares_the_expected_job_graph() -> None:
    jobs = _jobs()

    assert set(jobs) == {"gate", "sidecar", "bundle", "notarize"}
    assert jobs["bundle"]["needs"] == ["gate", "sidecar"]
    assert jobs["notarize"]["needs"] == ["bundle"]
    assert all(str(job["runs-on"]).startswith("macos-") for job in jobs.values())


def test_every_run_block_is_valid_shell() -> None:
    for name in _jobs():
        for step in _steps(name):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            result = subprocess.run(
                ["bash", "-n"], input=run, text=True, capture_output=True, check=False
            )
            assert result.returncode == 0, f"{name}/{step.get('name')}: {result.stderr}"


def test_run_blocks_avoid_bash_4_builtins() -> None:
    # GitHub's macOS runners ship bash 3.2 as /bin/bash.
    for name in _jobs():
        for step in _steps(name):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for builtin in ("mapfile", "readarray", "declare -A"):
                assert builtin not in run, f"{name}/{step.get('name')} uses {builtin}"


def test_gate_runs_lint_types_and_tests() -> None:
    commands = _commands("gate")

    assert "ruff check" in commands
    assert "ruff format --check" in commands
    assert "mypy" in commands
    assert "pytest" in commands


def test_bundle_job_refuses_to_ship_offline_databases() -> None:
    commands = _commands("bundle")

    assert "scripts/build_macos_app.sh" in commands
    assert "offline databases leaked into the bundle" in commands
    assert "codesign -v --deep --strict" in commands


def test_notarize_job_is_tag_gated_and_secret_gated() -> None:
    job = _jobs()["notarize"]

    assert "startsWith(github.ref, 'refs/tags/')" in str(job["if"])
    guarded = [
        step
        for step in _steps("notarize")
        if "steps.secrets.outputs.ready == 'true'" in str(step.get("if", ""))
    ]
    # Signing, notarizing and uploading all stay behind the secret check.
    assert len(guarded) >= 3
    commands = _commands("notarize")
    assert "notarytool submit" in commands
    assert "stapler staple" in commands
    assert "options runtime" in commands
