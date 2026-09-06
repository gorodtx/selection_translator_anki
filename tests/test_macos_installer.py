from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install_macos.sh"
LINUX_INSTALLER = REPO_ROOT / "scripts" / "install.sh"


def _text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_is_executable_and_syntactically_valid() -> None:
    assert INSTALLER.stat().st_mode & 0o111
    result = subprocess.run(
        ["bash", "-n", str(INSTALLER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "verb", ["install", "update", "remove", "rollback", "healthcheck"]
)
def test_installer_exposes_the_same_verbs_as_linux(verb: str) -> None:
    # Verb parity keeps the release runbook identical on both OSes.
    assert verb in _text()
    assert verb in LINUX_INSTALLER.read_text(encoding="utf-8")


def test_installer_adds_a_status_verb() -> None:
    assert "status_report" in _text()


def test_installer_verifies_database_checksums_before_installing() -> None:
    text = _text()

    assert "db-bundle.lock.json" in text
    assert "shasum -a 256" in text
    assert "checksum mismatch for ${filename}" in text
    # Partial downloads must never be promoted to the final name.
    assert 'tmp="${target}.part"' in text
    assert 'mv -f "${tmp}" "${target}"' in text


def test_installer_keeps_previous_release_and_can_roll_back() -> None:
    text = _text()

    assert 'mv "${RELEASES_DIR}/current" "${RELEASES_DIR}/previous"' in text
    assert "rollback()" in text
    assert "no previous release to roll back to" in text


def test_installer_removes_app_but_keeps_offline_bases() -> None:
    text = _text()
    remove_block = text[text.index("remove_app()") : text.index("healthcheck()")]

    assert 'rm -rf "${RELEASES_DIR}"' in remove_block
    # The 1.8 GB download is expensive; never delete it implicitly.
    assert 'rm -rf "${DB_DIR}"' not in remove_block.replace(
        'rm -rf \\"${DB_DIR}\\"', ""
    )
    assert "offline bases kept" in remove_block


def test_installer_registers_launch_agent_for_the_backend() -> None:
    text = _text()

    assert "com.translator.desktop.plist" in text
    assert "Contents/Resources/bin/run-backend" in text
    assert "launchctl bootstrap" in text and "launchctl bootout" in text
    assert "<key>KeepAlive</key>" in text


def test_launch_agent_pins_translator_directories() -> None:
    text = _text()
    agent_block = text[text.index("write_launch_agent()") : text.index("agent_load()")]

    # launchd inherits its own HOME, so the daemon must be told explicitly which
    # directories this install owns.
    for key in (
        "TRANSLATOR_CONFIG_DIR",
        "TRANSLATOR_DB_DIR",
        "TRANSLATOR_RUNTIME_DIR",
        "TRANSLATOR_LOG_DIR",
    ):
        assert key in agent_block, key


def test_healthcheck_waits_for_the_socket_before_failing() -> None:
    text = _text()
    block = text[text.index("healthcheck()") : text.index("status_report()")]

    assert 'while [[ ! -S "${socket}"' in block


def test_installer_unloads_agent_before_swapping_releases() -> None:
    text = _text()
    install_block = text[text.index("install_app()") : text.index("rollback()")]

    # Swapping the bundle under a running daemon leaves a stale socket.
    assert install_block.index("agent_unload") < install_block.index(
        'mv "${RELEASES_DIR}/current"'
    )
