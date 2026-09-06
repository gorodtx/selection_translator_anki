#!/bin/sh
# `swift test` on a machine that only has Command Line Tools (no Xcode).
# CLT ships Swift Testing but SwiftPM does not add its search paths automatically.
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
exec swift test "$@"
