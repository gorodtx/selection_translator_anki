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
  mkdir -p "$(dirname "${AGENT_PLIST}")" "${LOG_DIR}"
  cat > "${AGENT_PLIST}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${BUNDLE_ID}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RELEASES_DIR}/current/${APP_NAME}.app/Contents/Resources/bin/run-backend</string>
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

install_app() {
  [[ -d "${SOURCE_APP}" ]] || fail "app bundle not found: ${SOURCE_APP} (run scripts/build_macos_app.sh)"
  mkdir -p "${RELEASES_DIR}" "${LINK_DIR}"
  agent_unload
  if [[ -d "${RELEASES_DIR}/current" ]]; then
    rm -rf "${RELEASES_DIR}/previous"
    mv "${RELEASES_DIR}/current" "${RELEASES_DIR}/previous"
    log "kept previous release"
  fi
  mkdir -p "${RELEASES_DIR}/current"
  rsync -a --delete "${SOURCE_APP}/" "${RELEASES_DIR}/current/${APP_NAME}.app/"
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
  if [[ -S "${socket}" ]]; then
    log "OK: backend socket present"
  else
    log "FAIL: backend socket missing (${socket})"; status=1
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
