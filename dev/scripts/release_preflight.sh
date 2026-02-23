#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TAG="${1:-}"

log() {
  echo "[release-preflight] $*"
}

fail() {
  echo "[release-preflight] $*" >&2
  exit 1
}

usage() {
  cat <<USAGE
Usage:
  dev/scripts/release_preflight.sh vX.Y.Z
  dev/scripts/release_preflight.sh vX.Y.Z-rc.N

The script does not publish anything.
It validates immutable release constraints and builds release assets.
USAGE
}

require_tag() {
  [[ -n "${TAG}" ]] || fail "missing tag"
  if [[ ! "${TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]]; then
    fail "tag must match vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N"
  fi
}

ensure_immutable_target() {
  if git -C "${ROOT_DIR}" rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
    fail "tag already exists locally: ${TAG}"
  fi
  if git -C "${ROOT_DIR}" ls-remote --exit-code --tags origin "refs/tags/${TAG}" >/dev/null 2>&1; then
    fail "tag already exists on origin: ${TAG}"
  fi
  if command -v gh >/dev/null 2>&1; then
    local origin_url
    origin_url="$(git -C "${ROOT_DIR}" config --get remote.origin.url || true)"
    local repo_slug
    repo_slug="$(printf "%s" "${origin_url}" | sed -E 's#(git@github.com:|https://github.com/)##; s#\\.git$##')"
    if [[ -z "${repo_slug}" || "${repo_slug}" == "${origin_url}" ]]; then
      log "could not parse GitHub repo from origin URL; skipped GitHub release existence check"
      return
    fi
    if gh release view "${TAG}" --repo "${repo_slug}" >/dev/null 2>&1; then
      fail "GitHub release already exists for ${TAG}"
    fi
  else
    log "gh CLI not found; skipped GitHub release existence check"
  fi
}

build_assets() {
  TRANSLATOR_RELEASE_TAG="${TAG}" "${ROOT_DIR}/dev/scripts/build_release_assets.sh"
  (
    cd "${ROOT_DIR}/dev/dist/release/assets"
    sha256sum -c release-assets.sha256
  )
}

print_next_steps() {
  cat <<STEPS

Preflight passed for ${TAG}.

Next commands:
  git -C "${ROOT_DIR}" push origin main
  git -C "${ROOT_DIR}" tag ${TAG}
  git -C "${ROOT_DIR}" push origin ${TAG}
  gh release create ${TAG} \\
    --title "${TAG}" \\
    --generate-notes \\
    ${ROOT_DIR}/dev/dist/release/install.sh \\
    ${ROOT_DIR}/dev/dist/release/assets/release-assets.sha256 \\
    ${ROOT_DIR}/dev/dist/release/assets/translator-app.tar.gz \\
    ${ROOT_DIR}/dev/dist/release/assets/translator-extension.zip \\
    ${ROOT_DIR}/dev/dist/release/assets/primary.sqlite3 \\
    ${ROOT_DIR}/dev/dist/release/assets/fallback.sqlite3 \\
    ${ROOT_DIR}/dev/dist/release/assets/definitions_pack.sqlite3
STEPS
}

main() {
  if [[ "${TAG}" == "-h" || "${TAG}" == "--help" ]]; then
    usage
    exit 0
  fi
  require_tag
  ensure_immutable_target
  build_assets
  print_next_steps
}

main "$@"
