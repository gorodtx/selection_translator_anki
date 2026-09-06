#!/bin/sh
# Build Translator.app from the SwiftPM executable.
#
# SwiftPM emits a bare binary; macOS needs a bundle for LSUIElement (menu-bar only),
# NSServices (the "Translate with Translator" item on any selection) and code signing.
#
#   scripts/build_app.sh [debug|release]   -> .build/Translator.app
set -eu
cd "$(dirname "$0")/.."

CONFIG="${1:-release}"
APP_NAME="Translator"
BUNDLE_ID="com.gorodtx.translator"
OUT=".build/${APP_NAME}.app"

swift build -c "$CONFIG"
BIN="$(swift build -c "$CONFIG" --show-bin-path)/${APP_NAME}"
[ -x "$BIN" ] || { echo "binary not found: $BIN" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources"
cp "$BIN" "$OUT/Contents/MacOS/${APP_NAME}"
cp Resources/Info.plist "$OUT/Contents/Info.plist"
printf 'APPL????' > "$OUT/Contents/PkgInfo"

# Ad-hoc signature: enough for local runs (a Developer ID identity is needed for
# distribution and notarisation).
codesign --force --sign - --identifier "$BUNDLE_ID" --timestamp=none "$OUT" >/dev/null 2>&1 || \
  codesign --force --sign - "$OUT"

echo "$OUT"
