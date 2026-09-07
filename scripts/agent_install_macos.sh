#!/usr/bin/env bash
# One command that takes a checkout to a working install, for a person or an agent.
#
# Everything that can be done without a human is done here: build, install, verify the
# databases by checksum, start the login agent, wait for it, translate one word through
# it. What genuinely needs a human — the Accessibility grant, the offline language pair,
# an Apple Developer ID — is reported at the end as a machine-readable block, so an agent
# can decide what to do next instead of guessing.
#
#   scripts/agent_install_macos.sh            install and report
#   scripts/agent_install_macos.sh --report   report the current state only
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

APP_NAME="Translator"
SUPPORT_DIR="${HOME}/Library/Application Support/${APP_NAME}"
SOCKET_PATH="${TRANSLATOR_SOCKET_PATH:-${SUPPORT_DIR}/run/backend.sock}"
SFLTOOL_TIMEOUT_S="${TRANSLATOR_SFLTOOL_TIMEOUT_S:-5}"
INSTALLED_APP="${HOME}/Applications/${APP_NAME}.app"
REPORT_ONLY=0
[[ "${1:-}" == "--report" ]] && REPORT_ONLY=1

log() { printf '[agent-install] %s\n' "$*"; }
fail() { printf '[agent-install] FAILED: %s\n' "$*" >&2; exit 1; }

# --- prerequisites ----------------------------------------------------------------

check_prerequisites() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "macOS only; this is $(uname -s)"
  local major
  major="$(sw_vers -productVersion | cut -d. -f1)"
  [[ "${major}" -ge 26 ]] || fail "needs macOS 26 or newer for the on-device engines; this is $(sw_vers -productVersion)"
  command -v swift >/dev/null || fail "no Swift toolchain: install Xcode or the Command Line Tools (xcode-select --install)"
  command -v uv >/dev/null || fail "no uv: install it from https://docs.astral.sh/uv/"
  log "macOS $(sw_vers -productVersion), swift $(swift --version 2>&1 | head -1 | sed 's/.*version //; s/ .*//'), uv $(uv --version | awk '{print $2}')"
}

# --- steps ------------------------------------------------------------------------

build_and_install() {
  log "building the bundle (Swift shell, sidecar, embedded Python)"
  ./scripts/build_macos_app.sh >/dev/null || fail "build_macos_app.sh"
  log "installing (databases verified by sha256, downloaded only if missing)"
  ./scripts/install_macos.sh install || fail "install_macos.sh"
}

wait_for_backend() {
  log "waiting for the login agent to answer"
  local deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    if [[ -S "${SOCKET_PATH}" ]] && ping_backend >/dev/null 2>&1; then
      log "backend answered after $((SECONDS))s"
      return 0
    fi
    sleep 2
  done
  fail "backend did not answer within 90s; see ~/Library/Logs/${APP_NAME}/"
}

# Ask the backend one question and print the raw JSON result.
ping_backend() {
  uv run --frozen python - "${SOCKET_PATH}" <<'PY'
import json, socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(20)
sock.connect(sys.argv[1])
sock.sendall(b'{"id":1,"method":"ping","params":{}}\n')
buf = b""
while b"\n" not in buf:
    chunk = sock.recv(1 << 20)
    if not chunk:
        raise SystemExit("backend closed the connection")
    buf += chunk
print(json.dumps(json.loads(buf.split(b"\n", 1)[0])["result"], ensure_ascii=False))
PY
}

smoke_translate() {
  log "translating one word through the installed backend"
  uv run --frozen python - "${SOCKET_PATH}" <<'PY'
import json, socket, sys, time
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(0.5)
sock.connect(sys.argv[1])
sock.sendall(b'{"id":1,"method":"translate","params":{"text":"serendipity"}}\n')
buf, started, final = b"", time.perf_counter(), None
while time.perf_counter() - started < 15:
    try:
        buf += sock.recv(1 << 20)
    except (TimeoutError, OSError):
        continue
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        message = json.loads(line)
        if message.get("event") == "translation.state" and message["payload"]["phase"] == "final":
            state = message["payload"]["state"]
            final = state.get("translation_raw") or state.get("translation") or ""
    if final is not None:
        break
if not final:
    raise SystemExit("no translation came back")
print(f"[agent-install] translated 'serendipity' -> {final[:60]}")
PY
}

# --- report -----------------------------------------------------------------------

report() {
  local raw
  raw="$(ping_backend 2>/dev/null || echo '{}')"
  ACCESSIBILITY_GRANTED="$(accessibility_state)"
  # The program itself arrives on stdin, so the ping result cannot: it travels in the
  # environment instead. Piping into `python -` silently feeds the heredoc, not the data.
  PING_JSON="${raw}" ACCESSIBILITY="${ACCESSIBILITY_GRANTED}" APP="${INSTALLED_APP}" \
    LOGIN_ITEM="$(login_item_state)" \
    uv run --frozen python - <<'PY'
import json, os

ping = json.loads(os.environ.get("PING_JSON") or "{}")
db = ping.get("db") or {}
engines = ping.get("engines") or {}
accessibility = os.environ.get("ACCESSIBILITY", "unknown")
granted = accessibility == "yes"

# Everything an agent needs to decide what to do next, in one block it can parse.
state = {
    "installed_app": os.environ.get("APP", ""),
    "backend_running": bool(ping),
    "backend_version": ping.get("version", ""),
    "databases_present": all(bool(db.get(k)) for k in ("primary", "fallback", "definitions")),
    "database_dir": db.get("dir", ""),
    "apple_dictionary": bool(engines.get("apple_dictionary")),
    "dictionaries": engines.get("dictionaries", []),
    "apple_translation": bool(engines.get("apple_translation")),
    "translation_status": engines.get("translation_status", "unknown"),
    "login_item": os.environ.get("LOGIN_ITEM", "unknown"),
    "accessibility_granted": granted,
    # "unknown" means the app has not run since installing, not that it was refused.
    "accessibility_state": accessibility,
}
blocked, automatable = [], []
if not state["backend_running"]:
    blocked.append("backend is not answering; check ~/Library/Logs/Translator/")
if not state["databases_present"]:
    blocked.append("offline databases missing; re-run scripts/install_macos.sh")
if accessibility != "yes":
    automatable.append(
        "accessibility: open Settings > Setup and press Grant, or grant it to the app in "
        "System Settings > Privacy & Security > Accessibility. Until then the shortcut "
        "cannot read the selection; the Services menu still works."
    )
if not state["apple_translation"] and state["translation_status"] != "unsupported":
    automatable.append(
        "language pair: open Settings > Setup and press Download on the offline "
        "translation stage, then confirm in Apple's sheet. Until then phrases go over "
        "the network."
    )
if not state["apple_dictionary"]:
    automatable.append("apple dictionary: enable a Russian dictionary in Dictionary.app settings")
needs_purchase = [
    "apple developer id: only to give the build a team identity. Without it macOS "
    "announces the login item as coming from an unidentified developer. The item is "
    "still enabled and allowed, and the app works; nothing needs clicking."
]

print("=== TRANSLATOR_INSTALL_REPORT_BEGIN ===")
print(json.dumps(
    {"state": state, "blocked": blocked, "needs_human_click": automatable, "needs_purchase": needs_purchase},
    ensure_ascii=False, indent=2,
))
print("=== TRANSLATOR_INSTALL_REPORT_END ===")
if blocked:
    raise SystemExit(1)
PY
}

# How macOS recorded the login item. A name of "Translator" means the system tied the
# agent to this app; a bare program name means it could not, which is what the user sees
# in the notification.
# sfltool can wedge: measured hanging with no output at all while an earlier
# invocation was still stuck on the same store, 25 minutes and counting. This
# report must never be the thing that hangs — an agent waiting on it has
# nothing to fall back on — so the call gets a deadline. A check that did not
# answer reads as "unknown", which is already how an empty dump is treated:
# "could not look" is not "not registered".
run_with_deadline() {
  local seconds="$1"; shift
  local out; out="$(mktemp)"
  "$@" >"${out}" 2>/dev/null &
  local pid=$! ticks=0
  while kill -0 "${pid}" 2>/dev/null && (( ticks < seconds * 10 )); do
    sleep 0.1
    ticks=$((ticks + 1))
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 "${pid}" 2>/dev/null || true
    rm -f "${out}"
    return 1
  fi
  wait "${pid}" 2>/dev/null || true
  cat "${out}"
  rm -f "${out}"
}

login_item_state() {
  local dump
  dump="$(run_with_deadline "${SFLTOOL_TIMEOUT_S}" sfltool dumpbtm || true)"
  [[ -n "${dump}" ]] || { echo "unknown"; return; }
  if printf '%s' "${dump}" | /usr/bin/grep -q 'Executable Path:.*TranslatorBackend'; then
    echo "registered as Translator"
  elif printf '%s' "${dump}" | /usr/bin/grep -q 'com.translator.desktop'; then
    echo "registered, not attributed to the app"
  else
    echo "absent"
  fi
}

# Whether the app itself holds the Accessibility grant. Asking from a script would answer
# for the script's own parent, so the question goes to the installed bundle.
accessibility_state() {
  # The app records what it last saw; reading the TCC database needs Full Disk Access and
  # asking the question from here would answer for this shell, not for the app.
  local recorded
  recorded="$(defaults read com.translator.desktop accessibilityTrusted 2>/dev/null || true)"
  if [[ "${recorded}" == "1" ]]; then
    echo "yes"
  elif [[ "${recorded}" == "0" ]]; then
    echo "no"
  else
    # The app has not run yet, so nothing is known either way.
    echo "unknown"
  fi
}

# --- main -------------------------------------------------------------------------

if (( REPORT_ONLY == 0 )); then
  check_prerequisites
  build_and_install
  wait_for_backend
  smoke_translate
  log "installed at ${INSTALLED_APP}"
fi
report
