from __future__ import annotations

from pathlib import Path
import plistlib
import re
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_macos_app.sh"
RUN_SCRIPT = REPO_ROOT / "scripts" / "run_backend_macos.sh"


def _script() -> str:
    return BUILD_SCRIPT.read_text(encoding="utf-8")


def test_build_script_is_executable_and_strict() -> None:
    assert BUILD_SCRIPT.exists() and RUN_SCRIPT.exists()
    for script in (BUILD_SCRIPT, RUN_SCRIPT):
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"
        assert "set -euo pipefail" in script.read_text(encoding="utf-8")


def test_build_script_passes_shell_syntax_check() -> None:
    for script in (BUILD_SCRIPT, RUN_SCRIPT):
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr


def test_build_script_never_ships_offline_databases() -> None:
    text = _script()

    # The 1.8 GB bundle is downloaded into Application Support at first run;
    # shipping it inside the .app would break the immutable release contract.
    assert (
        'rm -rf "${RESOURCES}/app/translate_logic/infrastructure/language_base/offline_language_base"'
        in text
    )
    assert "db-bundle.lock.json" in text
    assert ".sqlite3" not in text


def test_build_script_embeds_runtime_and_sidecar() -> None:
    text = _script()

    assert "Resources/bin/apple-lang-helper" in text
    assert "TRANSLATOR_APPLE_HELPER" in text
    assert "runtime-requirements.txt" in text
    assert "desktop_app.platform.macos.daemon" in text
    for excluded in (
        "lib/python3.13/test",
        "lib/python3.13/idlelib",
        "lib/python3.13/tkinter",
    ):
        assert f"--exclude '{excluded}'" in text, excluded


def test_info_plist_declares_agent_service_and_minimum_os() -> None:
    text = _script()
    match = re.search(r"<\?xml.*?</plist>", text, re.DOTALL)
    assert match is not None, "Info.plist template not found"
    template = match.group(0)
    rendered = (
        template.replace("${APP_NAME}", "Translator")
        .replace("${BUNDLE_ID}", "com.translator.desktop")
        .replace("${APP_VERSION}", "0.3.0")
        .replace("${MIN_MACOS}", "26.0")
    )
    plist = plistlib.loads(rendered.encode("utf-8"))

    assert plist["CFBundleIdentifier"] == "com.translator.desktop"
    assert plist["LSUIElement"] is True
    assert plist["LSMinimumSystemVersion"] == "26.0"
    service = plist["NSServices"][0]
    assert service["NSMessage"] == "translateSelection"
    assert service["NSSendTypes"] == ["NSStringPboardType"]
    assert service["NSPortName"] == "Translator"


@pytest.mark.parametrize("directory", ["dist/", "macos/**/.build/"])
def test_build_outputs_are_git_ignored(directory: str) -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert directory in ignored


def test_build_script_strips_test_helpers_from_the_bundle() -> None:
    """A tool that imports a shipped test helper writes a .pyc beside it.

    That single file breaks the code seal, and `spctl` then reports the bundle
    as invalid rather than merely unsigned — which would fail notarisation far
    from the build.
    """
    text = _script()

    assert "-name 'test_*.py'" in text
    assert "-name 'pytest_plugin.py'" in text
    assert "-name 'conftest.py'" in text


def test_build_script_trims_versioned_tcl_packages() -> None:
    # The original globs only matched `lib/tcl*`, so `lib/thread3.0.6` and
    # friends rode along.
    text = _script()

    assert "-name 'thread*'" in text
    assert "-name 'libtcl*'" in text


def test_build_script_verifies_its_own_seal() -> None:
    text = _script()

    assert "codesign --verify --deep --strict" in text
    assert "the bundle signature is invalid" in text


def test_pytest_never_collects_from_build_output() -> None:
    """Collecting inside `dist/` imports from the bundle and breaks its seal."""
    conftest = (REPO_ROOT / "conftest.py").read_text(encoding="utf-8")

    assert '"dist",' in conftest
    assert '"out",' in conftest


@pytest.mark.skipif(
    not (REPO_ROOT / "dist" / "Translator.app").exists(),
    reason="no bundle built (scripts/build_macos_app.sh)",
)
def test_built_bundle_seal_is_intact() -> None:
    """Guards the whole toolchain: nothing may write into a signed bundle."""
    result = subprocess.run(
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            str(REPO_ROOT / "dist" / "Translator.app"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
