#!/usr/bin/env bash
# Development launcher: run the macOS backend daemon from the repository checkout.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
export TRANSLATOR_APPLE_HELPER="${TRANSLATOR_APPLE_HELPER:-${ROOT_DIR}/macos/AppleLangHelper/.build/release/apple-lang-helper}"
exec uv run --frozen python -m desktop_app.platform.macos.daemon "$@"
