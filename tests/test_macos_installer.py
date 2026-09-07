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
    assert 'BACKEND_LAUNCHER="TranslatorBackend"' in text
    assert "Contents/MacOS/${BACKEND_LAUNCHER}" in text
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


def test_healthcheck_asks_the_daemon_instead_of_stating_the_socket() -> None:
    """A socket file outlives the process that bound it.

    `kill -9` leaves the node on disk, so a stat-only check reports a healthy
    install with nothing listening — the one answer an agent-run install must
    never get wrong. Verified locally on both: an orphaned socket and the live
    one both satisfy `[[ -S ]]`, only the live one answers `ping`.
    """
    text = _text()
    block = text[text.index("healthcheck()") : text.index("status_report()")]

    assert "backend_answers" in block, "healthcheck must ask the daemon"
    assert '"method":"ping"' in text, "ping is the only side-effect-free method"
    # translate would leave a history entry behind on every healthcheck.
    assert '"method":"translate"' not in text


def test_installer_restarts_rather_than_reregisters_an_unchanged_agent() -> None:
    """Re-registering a login item on every update is churn macOS records.

    kickstart restarts the job; bootstrap registers it, and only the second
    touches the login item. Verified with a stubbed launchctl: two runs with an
    identical plist gave bootout, bootstrap, print, kickstart — no second
    registration; a plist whose path changed gave bootout, bootstrap twice; and
    when `launchctl print` fails, the unchanged case still falls back to
    bootout, bootstrap, because kickstart cannot start what is not loaded.
    """
    text = _text()
    block = text[text.index("agent_load()") : text.index("agent_unload()")]

    assert "kickstart -k" in block
    assert "AGENT_PLIST_CHANGED == 0" in block
    # The fallback has to stay: kickstart cannot help an un-bootstrapped agent.
    assert "launchctl bootstrap" in block
    # And the plist is only replaced when it actually differs.
    assert 'cmp -s "${staged}" "${AGENT_PLIST}"' in text


def test_install_does_not_deregister_the_login_item() -> None:
    """The branch that avoids re-registration has to be reachable on install.

    It was not: install_app booted the agent out before calling agent_load, and
    real launchctl refuses `print` for a booted-out agent, so every update fell
    back to bootout + bootstrap and recorded the login item afresh. A stubbed
    launchctl answered `print` with success after bootout and hid this — the
    stub was more forgiving than the system in the one place the branch turned
    on.

    Measured on a disposable agent: `print` fails after bootout. `launchctl
    kill` does keep the registration, and on this daemon KeepAlive does not
    respawn — it exits 0 on SIGTERM and {SuccessfulExit: false} leaves it "not
    running". The copy still goes to a staging directory because that safety
    would otherwise rest on the exit code staying 0: a job whose program dies
    by signal gets "spawn scheduled" instead, straight into a partial bundle.
    Three real installs after the change: "launch agent restarted (registration
    unchanged)" each time, pid 54995 -> 55876, healthcheck 0.
    """
    text = _text()
    block = text[text.index("install_app()") : text.index("rollback()")]

    assert "agent_unload" not in block, "install must not deregister the item"
    assert "agent_load" in block
    assert ".staging" in block, "nothing may read a half-copied release"


def test_installer_swaps_the_release_before_restarting_the_daemon() -> None:
    """The old daemon serves until the new files are in place, then is replaced.

    This used to unload the agent first, so that swapping under a running
    daemon could not leave a stale socket. The copy now lands in a staging
    directory and only the finished tree is moved into `current`, so the live
    release is never half-written and the unload is no longer the thing
    protecting it. Confirmed by running it: three installs, then healthcheck 0
    with "backend answers on the socket", and no .staging left behind.
    """
    text = _text()
    install_block = text[text.index("install_app()") : text.index("rollback()")]

    assert install_block.index('rsync -a --delete "${SOURCE_APP}/" "${staging}') < (
        install_block.index('mv "${staging}" "${RELEASES_DIR}/current"')
    )
    assert install_block.index('mv "${staging}"') < install_block.index("agent_load")
    # rollback and remove still deregister: there the item should go away.
    rest = text[text.index("rollback()") :]
    assert "agent_unload" in rest


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


def test_installer_refuses_a_plist_pointing_at_a_missing_launcher() -> None:
    """The staleness gate compares *.py and cannot see this one.

    The commit that moved launchd onto a signed Mach-O touched no Python, so a
    bundle built one commit earlier passes the gate as fresh while lacking the
    executable — and launchd would then point at nothing. Measured: with the
    launcher absent the function exits 1 and writes no plist; with it present
    the plist is written.
    """
    text = _text()
    block = text[text.index("write_launch_agent()") : text.index("<key>Label</key>")]

    assert "BACKEND_LAUNCHER" in block
    assert 'fail "bundle has no' in block


def test_build_signs_the_backend_launcher_before_sealing_the_bundle() -> None:
    text = BUILDER.read_text(encoding="utf-8")

    assert 'cp "${BACKEND_BIN}" "${CONTENTS}/MacOS/TranslatorBackend"' in text
    # A second Mach-O in Contents/MacOS is nested code, not a sealed resource, so an
    # unsigned one leaves the bundle seal broken and the login item unattributable.
    signing = text.index("TranslatorBackend" + '"', text.index("codesign"))
    sealing = text.index(
        'codesign "${SIGN_FLAGS[@]}" --identifier "${BUNDLE_ID}" "${APP_DIR}"'
    )
    assert signing < sealing, "the launcher must be signed before the bundle is sealed"
    assert '--identifier "${BUNDLE_ID}.backend"' in text


AGENT_INSTALLER = REPO_ROOT / "scripts" / "agent_install_macos.sh"


def test_agent_installer_is_executable_and_syntactically_valid() -> None:
    assert AGENT_INSTALLER.stat().st_mode & 0o111
    result = subprocess.run(
        ["bash", "-n", str(AGENT_INSTALLER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_agent_installer_never_waits_on_sfltool_without_a_deadline() -> None:
    """The report is all an agent gets, so it must not be able to hang.

    Measured: `sfltool dumpbtm` returned nothing and never exited — 25 minutes
    and counting on one invocation, while every later one blocked behind it.
    With the deadline the whole report finishes in 6s and answers exit 0.
    """
    text = AGENT_INSTALLER.read_text(encoding="utf-8")

    assert "run_with_deadline" in text
    # Every sfltool call goes through the deadline, none of them bare.
    for line in text.splitlines():
        if "sfltool" in line and not line.lstrip().startswith("#"):
            assert "run_with_deadline" in line, f"bare sfltool call: {line.strip()}"
    # A check that could not answer is "unknown", never "absent".
    assert 'echo "unknown"' in text


def test_agent_installer_still_reports_the_login_item_without_sfltool() -> None:
    """A tool that hangs must not cost the report its answer.

    `sfltool dumpbtm` is the only source for the name macOS shows the user, and it
    stopped answering mid-session: the binary itself still prints its usage, only the
    dump wedges. `launchctl print` costs nine milliseconds and knows what the agent
    runs, so the reliable half of the answer survives and "unknown" stays reserved for
    genuinely knowing nothing.
    """
    text = AGENT_INSTALLER.read_text(encoding="utf-8")
    body = text.split("login_item_state()", 1)[1].split("\n}", 1)[0]

    assert "launchctl print" in body
    # The fallback has to be able to name the launcher, or it reports nothing useful.
    assert "TranslatorBackend" in body
    # Order matters — reaching for launchctl only after the dump would let the hang cost
    # the answer anyway — and it has to be read from the code, not from a comment that
    # happens to mention the tool first.
    code = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )
    assert code.index("launchctl print") < code.index("sfltool")
