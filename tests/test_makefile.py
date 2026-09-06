"""The Makefile is the local mirror of the CI gate; keep it runnable."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"


def _targets() -> set[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    return set(re.findall(r"^([a-z][a-z0-9-]*):", text, re.M))


def _recipe(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{target}:.*\n((?:\t.*\n|\n)*)", text, re.M)
    assert match is not None, target
    return match.group(0)


@pytest.mark.parametrize(
    "target",
    ["bootstrap", "fmt", "fmt-check", "lint", "lint-check", "types", "test", "verify"],
)
def test_core_targets_exist(target: str) -> None:
    assert target in _targets()


@pytest.mark.parametrize(
    "target", ["macos-app", "macos-backend", "macos-swift", "macos-install"]
)
def test_macos_targets_exist(target: str) -> None:
    assert target in _targets()


def test_no_target_references_a_missing_tool() -> None:
    # `make verify` used to depend on tools/problems.py, which does not exist on
    # this branch, so the gate could never pass.
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "tools/problems.py" not in text
    assert "uv run ty check" not in text


def test_format_gate_is_scoped_to_changed_files() -> None:
    # Roughly twenty files inherited from the GNOME branch are not
    # ruff-formatted; a repo-wide format check can never go green here.
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "BASE ?= origin/gnome" in text
    assert "CHANGED_PY" in _recipe("fmt-check")
    assert "ruff format --check ." not in text


def test_verify_runs_lint_format_types_and_tests() -> None:
    line = next(
        line
        for line in MAKEFILE.read_text(encoding="utf-8").splitlines()
        if line.startswith("verify:")
    )

    assert set(line.split(":", 1)[1].split()) == {
        "lint-check",
        "fmt-check",
        "types",
        "test",
    }


def test_makefile_parses() -> None:
    result = subprocess.run(
        ["make", "-n", "--dry-run", "lint-check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ruff check" in result.stdout


def test_clean_removes_build_output_of_both_toolchains() -> None:
    recipe = _recipe("clean")

    assert "dist" in recipe
    assert "macos/AppleLangHelper/.build" in recipe
    assert "macos/Translator/.build" in recipe
