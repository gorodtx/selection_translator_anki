from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install_macos.sh"
LINUX_INSTALLER = REPO_ROOT / "scripts" / "install.sh"
BUILDER = REPO_ROOT / "scripts" / "build_macos_app.sh"


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
    # What launchd runs is what the user sees in Login Items, and a shell script carries
    # no signature: the system could not attribute one to this app and announced a bare
    # "run-backend" from an unidentified developer. It must be the signed executable.
    assert "Contents/MacOS/TranslatorBackend" in text
    assert "Contents/Resources/bin/run-backend" not in text
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


def test_installing_a_bundle_built_from_other_sources_is_refused() -> None:
    """A leftover `dist/` installs old code and the daemon answers from it.

    Nothing looks wrong from outside — the app runs, it is simply not the code
    that was just written. It cost half an hour of chasing a phantom defect in
    the other session, so the installer compares what the bundle carries
    against the working tree.
    """
    text = INSTALLER.read_text(encoding="utf-8")

    assert "assert_bundle_matches_tree" in text
    assert "TRANSLATOR_ALLOW_STALE_BUNDLE" in text
    assert "stale bundle" in text
    # The check has to run before anything is copied into place.
    body = text.split("install_app()", 1)[1].split("\n}", 1)[0]
    assert "assert_bundle_matches_tree" in body
    assert (
        body.index("assert_bundle_matches_tree") < body.index("rsync")
        if "rsync" in body
        else True
    )

def test_build_signs_the_backend_launcher_before_sealing_the_bundle() -> None:
    text = BUILDER.read_text(encoding="utf-8")

    assert 'cp "${BACKEND_BIN}" "${CONTENTS}/MacOS/TranslatorBackend"' in text
    # A second Mach-O in Contents/MacOS is nested code, not a sealed resource, so an
    # unsigned one leaves the bundle seal broken and the login item unattributable.
    signing = text.index("TranslatorBackend" + '"', text.index("codesign"))
    sealing = text.index('codesign "${SIGN_FLAGS[@]}" --identifier "${BUNDLE_ID}" "${APP_DIR}"')
    assert signing < sealing, "the launcher must be signed before the bundle is sealed"
    assert '--identifier "${BUNDLE_ID}.backend"' in text
