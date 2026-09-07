#!/usr/bin/env bash
# Assemble Translator.app for macOS: SwiftUI shell + Swift sidecar + embedded
# CPython runtime with the Python backend. Command Line Tools are enough; no
# Xcode required.
#
#   scripts/build_macos_app.sh [--out dist] [--python /path/to/cpython-root]
#                              [--skip-swift] [--sign IDENTITY]
#
# Layout produced:
#   Translator.app/Contents/
#     Info.plist
#     MacOS/Translator                      SwiftUI shell (macos/Translator)
#     Resources/bin/apple-lang-helper       Swift sidecar (macos/AppleLangHelper)
#     Resources/python/                     relocatable CPython (python-build-standalone)
#     Resources/app/{desktop_app,translate_logic}
#     Resources/site-packages/              runtime deps (scripts/runtime-requirements.txt)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/dist"
PYTHON_ROOT=""
SKIP_SWIFT=0
SIGN_IDENTITY="-"
APP_NAME="Translator"
BUNDLE_ID="com.translator.desktop"
APP_VERSION="${TRANSLATOR_APP_VERSION:-0.3.0}"
MIN_MACOS="26.0"

log() { printf '[build-macos] %s\n' "$*" >&2; }
fail() { log "error: $*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_DIR="$2"; shift 2 ;;
    --python) PYTHON_ROOT="$2"; shift 2 ;;
    --skip-swift) SKIP_SWIFT=1; shift ;;
    --sign) SIGN_IDENTITY="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

[[ "$(uname -s)" == "Darwin" ]] || fail "macOS only"
command -v swift >/dev/null || fail "swift toolchain not found (install Command Line Tools)"
command -v uv >/dev/null || fail "uv not found"

resolve_python_root() {
  if [[ -n "${PYTHON_ROOT}" ]]; then
    printf '%s\n' "${PYTHON_ROOT}"
    return
  fi
  local found
  found="$(uv python find 3.13 2>/dev/null || true)"
  [[ -n "${found}" ]] || fail "no CPython 3.13 managed by uv; run: uv python install 3.13"
  # .../cpython-3.13.x-macos-aarch64-none/bin/python3.13 -> package root
  local root
  root="$(cd "$(dirname "$(readlink -f "${found}")")/.." && pwd)"
  [[ -x "${root}/bin/python3.13" ]] || fail "unexpected python layout at ${root}"
  printf '%s\n' "${root}"
}

APP_DIR="${OUT_DIR}/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
RESOURCES="${CONTENTS}/Resources"
STAGE="${OUT_DIR}/.stage"

log "output: ${APP_DIR}"
rm -rf "${APP_DIR}" "${STAGE}"
mkdir -p "${CONTENTS}/MacOS" "${RESOURCES}/bin" "${RESOURCES}/app" "${STAGE}"

# --- Swift: sidecar + shell ---------------------------------------------------
if [[ "${SKIP_SWIFT}" -eq 0 ]]; then
  log "building apple-lang-helper"
  (cd "${ROOT_DIR}/macos/AppleLangHelper" && swift build -c release 2>&1 | tail -3 >&2)
  if [[ -d "${ROOT_DIR}/macos/Translator" ]]; then
    log "building Translator shell"
    (cd "${ROOT_DIR}/macos/Translator" && swift build -c release 2>&1 | tail -3 >&2)
  else
    log "macos/Translator not present yet; shell binary will be a placeholder launcher"
  fi
fi

HELPER_BIN="${ROOT_DIR}/macos/AppleLangHelper/.build/release/apple-lang-helper"
[[ -x "${HELPER_BIN}" ]] || fail "sidecar binary missing: ${HELPER_BIN}"
cp "${HELPER_BIN}" "${RESOURCES}/bin/apple-lang-helper"

SHELL_BIN="${ROOT_DIR}/macos/Translator/.build/release/Translator"
if [[ -x "${SHELL_BIN}" ]]; then
  cp "${SHELL_BIN}" "${CONTENTS}/MacOS/${APP_NAME}"
  # Swift resource bundles produced by SwiftPM (if any)
  for bundle in "${ROOT_DIR}"/macos/Translator/.build/release/*.bundle; do
    [[ -d "${bundle}" ]] && cp -R "${bundle}" "${RESOURCES}/"
  done
else
  # Headless placeholder: keeps the bundle runnable (backend only) until the
  # SwiftUI shell lands.
  cat > "${CONTENTS}/MacOS/${APP_NAME}" <<'LAUNCHER'
#!/bin/bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${HERE}/Resources/bin/run-backend"
LAUNCHER
  chmod +x "${CONTENTS}/MacOS/${APP_NAME}"
fi

# --- Python runtime ------------------------------------------------------------------
PY_ROOT="$(resolve_python_root)"
log "embedding CPython from ${PY_ROOT}"
mkdir -p "${RESOURCES}/python"
# rsync keeps symlinks (bin/python3 -> python3.13) and skips what the backend never needs.
rsync -a \
  --exclude 'lib/python3.13/test' \
  --exclude 'lib/python3.13/idlelib' \
  --exclude 'lib/python3.13/tkinter' \
  --exclude 'lib/python3.13/turtledemo' \
  --exclude 'lib/python3.13/ensurepip' \
  --exclude 'lib/python3.13/lib2to3' \
  --exclude 'lib/python3.13/site-packages' \
  --exclude 'lib/python3.13/config-3.13-darwin' \
  --exclude 'lib/python3.13/lib-dynload/_tkinter*' \
  --exclude 'lib/python3.13/__pycache__' \
  --exclude 'lib/pkgconfig' \
  --exclude 'lib/libpython3.13.a' \
  --exclude 'lib/tcl*' --exclude 'lib/tk*' --exclude 'lib/itcl*' --exclude 'lib/Tix*' \
  --exclude 'lib/libtcl*' --exclude 'lib/libtk*' \
  --exclude 'include' --exclude 'share' \
  "${PY_ROOT}/" "${RESOURCES}/python/"
find "${RESOURCES}/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
BUNDLED_PY="${RESOURCES}/python/bin/python3.13"
[[ -x "${BUNDLED_PY}" ]] || fail "bundled python missing"

# --- Backend sources + deps -------------------------------------------------------------
log "copying backend sources"
rsync -a --exclude '__pycache__' --exclude '*.pyc' \
  "${ROOT_DIR}/desktop_app" "${ROOT_DIR}/translate_logic" "${RESOURCES}/app/"
rm -rf "${RESOURCES}/app/translate_logic/infrastructure/language_base/offline_language_base"
mkdir -p "${RESOURCES}/app/translate_logic/infrastructure/language_base/offline_language_base"
touch "${RESOURCES}/app/translate_logic/infrastructure/language_base/offline_language_base/.gitkeep"

log "installing runtime requirements"
mkdir -p "${RESOURCES}/site-packages"
uv pip install --quiet --python "${BUNDLED_PY}" --target "${RESOURCES}/site-packages" \
  -r "${ROOT_DIR}/scripts/runtime-requirements.txt"
find "${RESOURCES}/site-packages" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "${RESOURCES}/site-packages" -type d \( -name 'tests' -o -name 'test' \) -prune -exec rm -rf {} +
# Test helpers are useless at runtime and actively harmful in a signed bundle:
# a tool that imports one writes a .pyc beside it and breaks the code seal.
find "${RESOURCES}/site-packages" -type f \
  \( -name 'test_*.py' -o -name '*_test.py' -o -name 'pytest_plugin.py' -o -name 'conftest.py' \) \
  -delete
# The earlier globs only matched lib/tcl*, so versioned Tcl packages survived.
find "${RESOURCES}/python/lib" -maxdepth 1 -type d \
  \( -name 'tcl*' -o -name 'tk*' -o -name 'itcl*' -o -name 'thread*' -o -name 'sqlite3.*' \) \
  -prune -exec rm -rf {} +
find "${RESOURCES}/python/lib" -maxdepth 1 -type f -name 'libtcl*' -delete
find "${RESOURCES}/python/lib" -maxdepth 1 -type f -name 'libtk*' -delete

log "byte-compiling backend"
"${BUNDLED_PY}" -m compileall -q -j 0 "${RESOURCES}/app" "${RESOURCES}/site-packages" >/dev/null

# --- Launch helpers -------------------------------------------------------------------------
cat > "${RESOURCES}/bin/run-backend" <<'RUNNER'
#!/bin/bash
# Starts the Python backend daemon from inside the bundle.
RES="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${RES}/app:${RES}/site-packages"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export TRANSLATOR_APPLE_HELPER="${RES}/bin/apple-lang-helper"
exec "${RES}/python/bin/python3.13" -m desktop_app.platform.macos.daemon "$@"
RUNNER
chmod +x "${RESOURCES}/bin/run-backend"

cp "${ROOT_DIR}/scripts/db-bundle.lock.json" "${RESOURCES}/db-bundle.lock.json"
cp "${ROOT_DIR}/scripts/runtime-requirements.txt" "${RESOURCES}/runtime-requirements.txt"

# --- Info.plist ------------------------------------------------------------------------------
cat > "${CONTENTS}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleExecutable</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${APP_VERSION}</string>
  <key>CFBundleVersion</key><string>${APP_VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>${MIN_MACOS}</string>
  <key>LSUIElement</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.reference</string>
  <key>NSHumanReadableCopyright</key><string>MIT License</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppleEventsUsageDescription</key><string>Translator reads the selected text of the frontmost app to translate it.</string>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key><dict><key>default</key><string>Translate with Translator</string></dict>
      <key>NSMessage</key><string>translateSelection</string>
      <key>NSPortName</key><string>${APP_NAME}</string>
      <key>NSSendTypes</key><array><string>NSStringPboardType</string></array>
      <key>NSRequiredContext</key><dict><key>NSTextContent</key><string>Word</string></dict>
    </dict>
  </array>
</dict>
</plist>
PLIST

# --- Signing -----------------------------------------------------------------------------------
log "signing (${SIGN_IDENTITY})"
find "${RESOURCES}/python" "${RESOURCES}/site-packages" -type f \( -name '*.so' -o -name '*.dylib' \) \
  -exec codesign --force --sign "${SIGN_IDENTITY}" {} + 2>/dev/null || true
codesign --force --sign "${SIGN_IDENTITY}" "${RESOURCES}/python/bin/python3.13"
codesign --force --sign "${SIGN_IDENTITY}" "${RESOURCES}/bin/apple-lang-helper"
codesign --force --sign "${SIGN_IDENTITY}" --identifier "${BUNDLE_ID}" "${APP_DIR}"

rm -rf "${STAGE}"

# A bundle with a broken seal is worse than an unsigned one: Gatekeeper rejects
# it and notarisation fails, both far from here. Catch it at the source.
log "verifying the seal"
if ! codesign --verify --deep --strict "${APP_DIR}" 2>&1 | tee "${OUT_DIR}/.codesign.log" >&2; then
  fail "the bundle signature is invalid (see ${OUT_DIR}/.codesign.log)"
fi
codesign --verify --deep --strict "${APP_DIR}" || fail "the bundle signature is invalid"

log "done: $(du -sh "${APP_DIR}" | cut -f1) at ${APP_DIR}"
