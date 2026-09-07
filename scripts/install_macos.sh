#!/usr/bin/env bash
# Installer for the macOS build: mirrors scripts/install.sh (Linux) — same
# current/previous release layout, same sha256-verified shared DB store, same
# healthcheck/rollback verbs.
#
#   scripts/install_macos.sh install|update|remove|rollback|healthcheck|status
#
# Layout:
#   ~/Library/Application Support/Translator/
#     releases/{current,previous}/Translator.app
#     db/{primary,fallback,definitions_pack}.sqlite3   (shared, verified)
#   ~/Applications/Translator.app -> releases/current/Translator.app
#   ~/Library/LaunchAgents/com.translator.desktop.plist
set -euo pipefail

APP_NAME="Translator"
BUNDLE_ID="com.translator.desktop"
SUPPORT_DIR="${HOME}/Library/Application Support/${APP_NAME}"
RELEASES_DIR="${SUPPORT_DIR}/releases"
# The app resolves databases through TRANSLATOR_DB_DIR (see platform/paths.py), so the
# installer has to honour the same override: without it a store that already holds the
# 1.8 GB bundle is invisible here and every install re-downloads it.
DB_DIR="${TRANSLATOR_DB_DIR:-${SUPPORT_DIR}/db}"
LINK_DIR="${HOME}/Applications"
AGENT_PLIST="${HOME}/Library/LaunchAgents/${BUNDLE_ID}.plist"
LOG_DIR="${HOME}/Library/Logs/${APP_NAME}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_BUNDLE_LOCK_PATH="${TRANSLATOR_DB_BUNDLE_LOCK_PATH:-${ROOT_DIR}/scripts/db-bundle.lock.json}"
SOURCE_APP="${TRANSLATOR_APP_PATH:-${ROOT_DIR}/dist/${APP_NAME}.app}"
DB_FILES=("primary.sqlite3" "fallback.sqlite3" "definitions_pack.sqlite3")
# The signed Mach-O launchd starts; a shell script cannot carry a signature.
BACKEND_LAUNCHER="TranslatorBackend"
AGENT_PLIST_CHANGED=1
# Long enough for a cold daemon that waits on the first engine probe (capped at 5s).
PING_TIMEOUT_S="${TRANSLATOR_PING_TIMEOUT_S:-8}"

log() { printf '[translator] %s\n' "$*" >&2; }
fail() { log "error: $*"; exit 1; }

require_macos() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "macOS only"
}

lock_value() {
  local mode="$1" key="${2:-}"
  [[ -s "${DB_BUNDLE_LOCK_PATH}" ]] || fail "db bundle lock not found: ${DB_BUNDLE_LOCK_PATH}"
  python3 - "${DB_BUNDLE_LOCK_PATH}" "${mode}" "${key}" <<'PY'
import json, pathlib, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
mode, key = sys.argv[2], sys.argv[3]
if mode == "repo":
    print(payload["repo"])
elif mode == "tag":
    print(payload["tag"])
elif mode == "sha":
    print(payload["assets"][key]["sha256"])
PY
}

sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }

ensure_db_file() {
  local filename="$1"
  local target="${DB_DIR}/${filename}"
  local expected
  expected="$(lock_value sha "${filename}")"
  if [[ -f "${target}" ]] && [[ "$(sha256_of "${target}")" == "${expected}" ]]; then
    log "offline base ok: ${filename}"
    return 0
  fi
  local repo tag url tmp
  repo="$(lock_value repo)"
  tag="$(lock_value tag)"
  url="https://github.com/${repo}/releases/download/${tag}/${filename}"
  tmp="${target}.part"
  mkdir -p "${DB_DIR}"
  log "downloading ${filename} from ${tag}"
  curl -fL --retry 5 --retry-delay 3 --retry-all-errors -C - -o "${tmp}" "${url}"
  local actual
  actual="$(sha256_of "${tmp}")"
  [[ "${actual}" == "${expected}" ]] || { rm -f "${tmp}"; fail "checksum mismatch for ${filename}"; }
  mv -f "${tmp}" "${target}"
  log "offline base installed: ${filename}"
}

ensure_databases() {
  for filename in "${DB_FILES[@]}"; do
    ensure_db_file "${filename}"
  done
}

write_launch_agent() {
  # The plist names a binary inside the bundle, so a bundle without it leaves
  # launchd pointing at nothing and the app never starts. The staleness gate
  # cannot see this: it compares *.py, and the commit that introduced the
  # launcher touched no Python at all — a bundle built one commit earlier passes
  # as fresh and still lacks the executable.
  local program="${RELEASES_DIR}/current/${APP_NAME}.app/Contents/MacOS/${BACKEND_LAUNCHER}"
  [[ -x "${program}" ]] || fail "bundle has no ${BACKEND_LAUNCHER}: rebuild it (make macos-app) — ${program}"
  mkdir -p "$(dirname "${AGENT_PLIST}")" "${LOG_DIR}"
  local staged; staged="$(mktemp)"
  cat > "${staged}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${BUNDLE_ID}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RELEASES_DIR}/current/${APP_NAME}.app/Contents/MacOS/${BACKEND_LAUNCHER}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TRANSLATOR_CONFIG_DIR</key><string>${SUPPORT_DIR}</string>
    <key>TRANSLATOR_DB_DIR</key><string>${DB_DIR}</string>
    <key>TRANSLATOR_RUNTIME_DIR</key><string>${SUPPORT_DIR}/run</string>
    <key>TRANSLATOR_LOG_DIR</key><string>${LOG_DIR}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>${LOG_DIR}/launchd.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/launchd.err.log</string>
</dict>
</plist>
PLIST
  # Re-registering a login item is not free: every bootout/bootstrap pair makes
  # macOS record the item afresh, and ten update cycles in one session left this
  # machine's BTM store wedged — `sfltool dumpbtm` hangs on it while every other
  # sfltool subcommand answers. Unproven as the cause, but needless churn either
  # way: an unchanged plist needs no new registration, only a restarted process.
  if [[ -f "${AGENT_PLIST}" ]] && cmp -s "${staged}" "${AGENT_PLIST}"; then
    AGENT_PLIST_CHANGED=0
    rm -f "${staged}"
  else
    AGENT_PLIST_CHANGED=1
    mv "${staged}" "${AGENT_PLIST}"
  fi
}

# launchd is not scoped by $HOME: the label is per user, so an install run with
# a redirected HOME — which is how anyone tests this — would bootout the real
# installation and then bootstrap a plist from the sandbox. That silently
# breaks the working setup. Touch launchd only when HOME really is the account's
# home directory.
real_home() {
  local home
  home="$(dscl . -read "/Users/$(id -un)" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
  printf '%s\n' "${home:-${HOME}}"
}

launchd_is_ours() {
  [[ "${HOME}" == "$(real_home)" ]]
}

agent_load() {
  if ! launchd_is_ours; then
    log "HOME is not the account home; leaving launchd alone (agent not loaded)"
    log "plist written to ${AGENT_PLIST}; load it by hand if that is what you meant"
    return 0
  fi
  # kickstart restarts the job; bootstrap registers it. Only the second one
  # touches the login item, so prefer the first whenever the registration is
  # already correct. kickstart cannot help an un-bootstrapped agent, hence the
  # fallback rather than a bare choice.
  if (( AGENT_PLIST_CHANGED == 0 )) \
    && launchctl print "gui/$(id -u)/${BUNDLE_ID}" >/dev/null 2>&1 \
    && launchctl kickstart -k "gui/$(id -u)/${BUNDLE_ID}" >/dev/null 2>&1; then
    log "launch agent restarted (registration unchanged)"
    return 0
  fi
  launchctl bootout "gui/$(id -u)/${BUNDLE_ID}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "${AGENT_PLIST}"
  log "launch agent loaded"
}

agent_unload() {
  if ! launchd_is_ours; then
    log "HOME is not the account home; leaving launchd alone (agent not unloaded)"
    return 0
  fi
  launchctl bootout "gui/$(id -u)/${BUNDLE_ID}" 2>/dev/null || true
}

# A bundle carries a copy of the Python sources, so a `dist/` left over from an
# earlier commit installs old code and the daemon then answers from it. That is
# invisible from the outside: the app runs, it is simply not the code you just
# wrote. Compare what the bundle carries against the working tree.
assert_bundle_matches_tree() {
  local bundled="${SOURCE_APP}/Contents/Resources/app"
  [[ -d "${bundled}" ]] || return 0
  local tree_sum bundle_sum
  tree_sum="$(cd "${ROOT_DIR}" && find desktop_app translate_logic -name '*.py' -type f \
    -exec shasum -a 256 {} + | sort -k2 | shasum -a 256 | cut -d' ' -f1)"
  bundle_sum="$(cd "${bundled}" && find desktop_app translate_logic -name '*.py' -type f \
    -exec shasum -a 256 {} + | sort -k2 | shasum -a 256 | cut -d' ' -f1)"
  if [[ "${tree_sum}" != "${bundle_sum}" ]]; then
    log "the bundle in ${SOURCE_APP} was built from different sources than the"
    log "working tree, so installing it would run stale code."
    log "rebuild first: scripts/build_macos_app.sh --out $(dirname "${SOURCE_APP}")"
    log "or set TRANSLATOR_ALLOW_STALE_BUNDLE=1 if that is deliberate"
    [[ "${TRANSLATOR_ALLOW_STALE_BUNDLE:-}" == "1" ]] || fail "stale bundle"
    log "installing a stale bundle on request"
  fi
}

install_app() {
  [[ -d "${SOURCE_APP}" ]] || fail "app bundle not found: ${SOURCE_APP} (run scripts/build_macos_app.sh)"
  assert_bundle_matches_tree
  mkdir -p "${RELEASES_DIR}" "${LINK_DIR}"
  # Copy into a staging directory and swap it in, rather than unloading the
  # agent and rsyncing over the live release. Booting the agent out is the churn
  # worth avoiding — it deregisters the login item on every update — and the
  # obvious alternative, stopping the daemon first, is safe only by accident:
  # the daemon handles SIGTERM and exits 0 (measured), and KeepAlive here is
  # {SuccessfulExit: false}, so launchd leaves it "not running" rather than
  # respawning. Let that handler go away, or let the daemon die on a signal
  # instead, and launchd schedules a spawn straight into a half-copied bundle
  # (measured too, on a job whose program dies by signal: "spawn scheduled").
  # Staging depends on none of that: nothing stops, nothing reads a partly
  # written `current`, and the swap is one `mv`.
  local staging="${RELEASES_DIR}/.staging"
  rm -rf "${staging}"
  mkdir -p "${staging}"
  rsync -a --delete "${SOURCE_APP}/" "${staging}/${APP_NAME}.app/"
  if [[ -d "${RELEASES_DIR}/current" ]]; then
    rm -rf "${RELEASES_DIR}/previous"
    mv "${RELEASES_DIR}/current" "${RELEASES_DIR}/previous"
    log "kept previous release"
  fi
  mv "${staging}" "${RELEASES_DIR}/current"
  ln -sfn "${RELEASES_DIR}/current/${APP_NAME}.app" "${LINK_DIR}/${APP_NAME}.app"
  ensure_databases
  write_launch_agent
  agent_load
  log "installed to ${LINK_DIR}/${APP_NAME}.app"
}

rollback() {
  [[ -d "${RELEASES_DIR}/previous" ]] || fail "no previous release to roll back to"
  agent_unload
  rm -rf "${RELEASES_DIR}/.rollback"
  mv "${RELEASES_DIR}/current" "${RELEASES_DIR}/.rollback"
  mv "${RELEASES_DIR}/previous" "${RELEASES_DIR}/current"
  mv "${RELEASES_DIR}/.rollback" "${RELEASES_DIR}/previous"
  ln -sfn "${RELEASES_DIR}/current/${APP_NAME}.app" "${LINK_DIR}/${APP_NAME}.app"
  agent_load
  log "rolled back"
}

remove_app() {
  agent_unload
  rm -f "${AGENT_PLIST}" "${LINK_DIR}/${APP_NAME}.app"
  rm -rf "${RELEASES_DIR}"
  log "removed app; offline bases kept in ${DB_DIR}"
  if [[ -n "${TRANSLATOR_DB_DIR:-}" ]]; then
    # The store was supplied from outside, so it is not ours to suggest
    # deleting: the same directory is very likely the user's only copy.
    log "the base store is external (TRANSLATOR_DB_DIR); leaving it untouched"
  else
    log "delete them with: rm -rf \"${DB_DIR}\""
  fi
}

# A socket file outlives the process that bound it: kill -9 the daemon and the
# node stays behind, so `[[ -S ... ]]` reports a healthy install where nothing
# is listening. Ask the daemon instead. `ping` is the only method with no side
# effects — `translate` would leave an entry in the user's history on every
# healthcheck.
backend_answers() {
  local socket="$1" reply
  reply="$(printf '%s\n' '{"id":1,"method":"ping","params":{}}' \
    | nc -U "${socket}" -w "${PING_TIMEOUT_S}" 2>/dev/null || true)"
  # Test the payload, never the pipeline's exit code: that belongs to nc.
  [[ "${reply}" == *'"ok":true'* ]]
}

healthcheck() {
  local status=0
  local socket="${SUPPORT_DIR}/run/backend.sock"
  # launchd needs a moment to start the daemon right after bootstrap.
  local waited=0
  while [[ ! -S "${socket}" && "${waited}" -lt 10 ]]; do
    sleep 1
    waited=$((waited + 1))
  done
  [[ -d "${RELEASES_DIR}/current/${APP_NAME}.app" ]] || { log "FAIL: no current release"; status=1; }
  for filename in "${DB_FILES[@]}"; do
    if [[ -f "${DB_DIR}/${filename}" ]]; then
      log "OK: ${filename}"
    else
      log "FAIL: missing ${filename}"; status=1
    fi
  done
  if [[ ! -S "${socket}" ]]; then
    log "FAIL: backend socket missing (${socket})"; status=1
  elif backend_answers "${socket}"; then
    log "OK: backend answers on the socket"
  else
    log "FAIL: backend socket exists but nothing answers (${socket})"; status=1
  fi
  launchctl print "gui/$(id -u)/${BUNDLE_ID}" >/dev/null 2>&1 \
    && log "OK: launch agent running" || { log "FAIL: launch agent not running"; status=1; }
  return "${status}"
}

status_report() {
  log "support dir: ${SUPPORT_DIR}"
  [[ -d "${RELEASES_DIR}/current" ]] && log "current: $(du -sh "${RELEASES_DIR}/current" | cut -f1)"
  [[ -d "${RELEASES_DIR}/previous" ]] && log "previous: $(du -sh "${RELEASES_DIR}/previous" | cut -f1)"
  [[ -d "${DB_DIR}" ]] && log "databases: $(du -sh "${DB_DIR}" | cut -f1)"
  return 0
}

main() {
  require_macos
  case "${1:-install}" in
    install|update) install_app ;;
    rollback) rollback ;;
    remove) remove_app ;;
    healthcheck) healthcheck ;;
    status) status_report ;;
    *) fail "usage: $0 install|update|remove|rollback|healthcheck|status" ;;
  esac
}

main "$@"
