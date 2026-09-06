#!/bin/sh
# Runs `swift test` on a machine that only has Command Line Tools (no Xcode).
# CLT ships Swift Testing but hides it from SwiftPM; point the compiler and the loader at it.
set -eu
cd "$(dirname "$0")/.."
CLT="$(xcode-select -p 2>/dev/null || echo /Library/Developer/CommandLineTools)"
FW="$CLT/Library/Developer/Frameworks"
LIB="$CLT/Library/Developer/usr/lib"
if [ -d "$FW/Testing.framework" ]; then
  exec swift test \
    -Xswiftc -F"$FW" \
    -Xlinker -F"$FW" \
    -Xlinker -rpath -Xlinker "$FW" \
    -Xlinker -rpath -Xlinker "$LIB" \
    "$@"
fi
# Full Xcode: the toolchain already knows where Testing lives.
exec swift test "$@"
