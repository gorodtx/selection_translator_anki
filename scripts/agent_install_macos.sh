#!/usr/bin/env bash
# One command that takes a checkout to a working app, for a human or an agent.
#
#   scripts/agent_install_macos.sh [--skip-build] [--json]
#
# Builds both Swift targets and the bundle, installs it, starts the launchd
# agent, health-checks, then prints what is left for a person — the steps that
# need a permission or an Apple account and cannot be automated from a shell.
# Never prompts. Exit code 0 means the app is installed and answering, even if
# some optional step is still pending; a non-zero code means it is not.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

SKIP_BUILD=0
AS_JSON=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    --json) AS_JSON=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done

SUPPORT_DIR="${HOME}/Library/Application Support/Translator"
DB_DIR="${TRANSLATOR_DB_DIR:-${SUPPORT_DIR}/db}"
APP="${SUPPORT_DIR}/releases/current/Translator.app"
HELPER="${APP}/Contents/Resources/bin/apple-lang-helper"

step() { printf '\n[agent-install] == %s ==\n' "$*" >&2; }
note() { printf '[agent-install] %s\n' "$*" >&2; }
fail() { printf '[agent-install] error: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "macOS only"
command -v swift >/dev/null || fail "swift not found (install the Command Line Tools)"
command -v uv >/dev/null || fail "uv not found: https://docs.astral.sh/uv/"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  step "building"
  (cd macos/AppleLangHelper && swift build -c release >/dev/null 2>&1) \
    || fail "the sidecar did not build"
  (cd macos/Translator && swift build -c release >/dev/null 2>&1) \
    || fail "the SwiftUI shell did not build"
  scripts/build_macos_app.sh --out dist >/dev/null 2>&1 || fail "the bundle did not build"
  note "bundle: $(du -sh dist/Translator.app | cut -f1)"
fi

step "installing"
# The installer downloads the offline bases on first run (about 1.8 GB) and
# verifies every one against scripts/db-bundle.lock.json.
scripts/install_macos.sh install >&2 || fail "install failed"

step "health"
scripts/install_macos.sh healthcheck >&2 || fail "healthcheck failed"

# --- what is left for a person ------------------------------------------------
# Each probe answers from the live machine, never from an assumption.

language_pair="unknown"
if [[ -x "${HELPER}" ]]; then
  language_pair="$(
    printf '{"id":"1","op":"availability","source":"en","target":"ru"}\n' \
      | "${HELPER}" 2>/dev/null \
      | /usr/bin/python3 -c 'import json,sys
try:
    body = json.loads(sys.stdin.readline())
    print(body.get("result", {}).get("status", "unknown") if body.get("ok") else "unknown")
except Exception:
    print("unknown")' 2>/dev/null || echo unknown
  )"
fi

anki="absent"
if /usr/bin/nc -z 127.0.0.1 8765 >/dev/null 2>&1; then
  anki="reachable"
elif [[ -f "${HOME}/Library/Application Support/Anki2/addons21/2055492159/config.json" ]]; then
  anki="installed_not_running"
fi

signing="absent"
if security find-identity -v -p codesigning 2>/dev/null | grep -q "Developer ID Application"; then
  signing="present"
fi

databases="ok"
for filename in primary.sqlite3 fallback.sqlite3 definitions_pack.sqlite3; do
  [[ -f "${DB_DIR}/${filename}" ]] || databases="incomplete"
done

emit_json() {
  /usr/bin/python3 - "$@" <<'PY'
import json, sys
language_pair, anki, signing, databases, app = sys.argv[1:6]
pending = []
if language_pair != "installed":
    pending.append({
        "id": "language_pair",
        "state": language_pair,
        "why": "Apple's on-device translator needs the en->ru pair downloaded once.",
        "who": "person",
        "how": "Open the app's Settings and press Download next to Apple Translation, "
               "or System Settings > General > Language & Region > Translation Languages.",
    })
if anki != "reachable":
    pending.append({
        "id": "anki_connect",
        "state": anki,
        "why": "Cards are added through AnkiConnect on 127.0.0.1:8765.",
        "who": "person",
        "how": "Install Anki and the AnkiConnect add-on (code 2055492159), then leave Anki running.",
    })
if signing != "present":
    pending.append({
        "id": "developer_id",
        "state": signing,
        "why": "Notarisation needs a Developer ID; the local build is ad-hoc signed and Gatekeeper rejects it elsewhere.",
        "who": "person",
        "how": "Join the Apple Developer Program, then tag a release so CI notarises it.",
    })
pending.append({
    "id": "accessibility",
    "state": "check_in_app",
    "why": "Reading the selection needs Accessibility. Without it the Services menu item still works, "
           "but the global shortcut cannot read a selection.",
    "who": "person",
    "how": "The app asks on first use; or System Settings > Privacy & Security > Accessibility.",
})
print(json.dumps({
    "installed": True,
    "app": app,
    "databases": databases,
    "engines": {"language_pair": language_pair},
    "pending": pending,
}, ensure_ascii=False, indent=2))
PY
}

step "what is left for a person"
if [[ "${AS_JSON}" -eq 1 ]]; then
  emit_json "${language_pair}" "${anki}" "${signing}" "${databases}" "${APP}"
else
  emit_json "${language_pair}" "${anki}" "${signing}" "${databases}" "${APP}" >&2
  note "app: ${APP}"
  note "open it with: open \"${APP}\""
fi
