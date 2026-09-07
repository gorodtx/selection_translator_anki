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


def test_installer_reuses_an_existing_database_store() -> None:
    """The app resolves databases through TRANSLATOR_DB_DIR, so the installer must too.

    Deriving the directory from HOME alone made a store that already held the 1.8 GB
    bundle invisible, and every install re-downloaded the lot.
    """
    text = _text()

    assert 'DB_DIR="${TRANSLATOR_DB_DIR:-${SUPPORT_DIR}/db}"' in text
    # The chosen directory is also what the agent gets pinned to, so the backend and
    # the installer never disagree about where the databases live.
    assert "<key>TRANSLATOR_DB_DIR</key><string>${DB_DIR}</string>" in text


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


def test_remove_does_not_suggest_deleting_an_external_store() -> None:
    """With `TRANSLATOR_DB_DIR` set, the store is very likely the user's only

    copy of 1.8 GB; printing `rm -rf` at it is a footgun even when accurate.
    """
    text = INSTALLER.read_text(encoding="utf-8")

    assert 'if [[ -n "${TRANSLATOR_DB_DIR:-}" ]]; then' in text
    assert "the base store is external" in text


def test_launchd_is_left_alone_when_home_is_redirected() -> None:
    """launchd labels are per account, not per `$HOME`.

    An install run with a redirected HOME — which is how anyone tests it —
    used to `bootout` the real installation by label and then bootstrap a
    plist from the sandbox, silently breaking the working setup.
    """
    text = INSTALLER.read_text(encoding="utf-8")

    assert "launchd_is_ours()" in text
    assert "NFSHomeDirectory" in text
    assert text.count("leaving launchd alone") == 2  # load and unload
    # The guard has to come before every launchctl call that mutates state.
    for block in ("agent_load()", "agent_unload()"):
        body = text.split(block, 1)[1].split("\n}", 1)[0]
        assert "launchd_is_ours" in body, block
        assert body.index("launchd_is_ours") < body.index("launchctl"), block


def test_agent_install_script_is_present_and_strict() -> None:
    script = REPO_ROOT / "scripts" / "agent_install_macos.sh"

    assert script.exists() and script.stat().st_mode & 0o111
    text = script.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_agent_install_reports_every_manual_step() -> None:
    """An agent needs the leftovers as data, not prose."""
    text = (REPO_ROOT / "scripts" / "agent_install_macos.sh").read_text(
        encoding="utf-8"
    )

    for item in ("language_pair", "anki_connect", "developer_id", "accessibility"):
        assert f'"id": "{item}"' in text, item
    # Every entry says who has to act and how, so the caller need not guess.
    assert '"who": "person"' in text
    assert text.count('"how"') >= 4
    # Never interactive: an agent cannot answer a prompt.
    assert "read -p" not in text and "read -r" not in text
