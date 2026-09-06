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

    assert set(jobs) == {
        "gate",
        "linux-parity",
        "sidecar",
        "shell",
        "bundle",
        "notarize",
    }
    assert jobs["bundle"]["needs"] == ["gate", "sidecar", "shell", "linux-parity"]
    assert jobs["notarize"]["needs"] == ["bundle"]
    assert jobs["linux-parity"]["runs-on"] == "ubuntu-latest"
    assert all(
        str(job["runs-on"]).startswith("macos-")
        for name, job in jobs.items()
        if name != "linux-parity"
    )
    # Swift jobs need the macOS 26 SDK for TranslationSession(installedSource:).
    assert jobs["sidecar"]["runs-on"] == "macos-26"
    assert jobs["shell"]["runs-on"] == "macos-26"
    assert jobs["bundle"]["runs-on"] == "macos-26"


def test_shell_job_builds_tests_and_checks_protocol_parity() -> None:
    commands = _commands("shell")

    assert "swift build -c release" in commands
    assert "scripts/swift-test.sh" in commands
    assert "swift shell is missing" in commands


def test_bundle_verifies_a_real_shell_binary_not_the_placeholder() -> None:
    commands = _commands("bundle")

    assert 'test -x "${app}/Contents/MacOS/Translator"' in commands
    assert "Mach-O" in commands


def test_linux_job_proves_the_engine_is_not_forked() -> None:
    commands = _commands("linux-parity")

    assert "pytest" in commands
    assert "mypy" in commands
    assert "apple engines must stay off on Linux" in commands
    assert "/tmp/cfg/translator" in commands


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

    # The gate must cover every Python file in the repo, not a hand-picked list:
    # macos/Translator/scripts/mock_backend.py slipped past a narrower check.
    assert "ruff check ." in commands
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
