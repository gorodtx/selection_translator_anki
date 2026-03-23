#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="${ROOT_DIR}/dev/dist/db_bundle"
ASSETS_DIR="${DIST_DIR}"

ALLOW_DIRTY_RELEASE="${TRANSLATOR_RELEASE_ALLOW_DIRTY:-0}"
RELEASE_REPO="${TRANSLATOR_RELEASE_REPO:-gorodtx/selection_translator_anki}"
DB_BUNDLE_LOCK_PATH="${TRANSLATOR_DB_BUNDLE_LOCK_PATH:-${ROOT_DIR}/scripts/db-bundle.lock.json}"
WRITE_LOCK="${TRANSLATOR_DB_BUNDLE_WRITE_LOCK:-0}"

log() {
  echo "[db-bundle-build] $*"
}

fail() {
  echo "[db-bundle-build] $*" >&2
  exit 1
}

ensure_clean_tracked_tree() {
  if [[ "${ALLOW_DIRTY_RELEASE}" == "1" ]]; then
    log "dirty tracked tree is allowed by TRANSLATOR_RELEASE_ALLOW_DIRTY=1"
    return
  fi
  if ! git -C "${ROOT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail "not a git work tree: ${ROOT_DIR}"
  fi
  if ! git -C "${ROOT_DIR}" diff --quiet --ignore-submodules HEAD --; then
    fail "tracked changes detected. Commit/stash before building db bundle assets."
  fi
  if ! git -C "${ROOT_DIR}" diff --cached --quiet --ignore-submodules --; then
    fail "staged changes detected. Commit/stash before building db bundle assets."
  fi
}

main() {
  ensure_clean_tracked_tree
  rm -rf "${DIST_DIR}"
  mkdir -p "${ASSETS_DIR}"

  local args=(
    python3
    "${ROOT_DIR}/dev/scripts/release_metadata.py"
    build-db-bundle
    --repo "${RELEASE_REPO}"
    --assets-dir "${ASSETS_DIR}"
    --out-file "${DIST_DIR}/db-bundle.lock.json"
  )
  if [[ "${WRITE_LOCK}" == "1" ]]; then
    args+=(--write-lock "${DB_BUNDLE_LOCK_PATH}")
  fi

  local bundle_tag
  bundle_tag="$("${args[@]}")"
  log "built ${DIST_DIR}/db-bundle.lock.json"
  if [[ "${WRITE_LOCK}" == "1" ]]; then
    log "updated ${DB_BUNDLE_LOCK_PATH}"
  fi
  log "bundle tag: ${bundle_tag}"
  log "upload: primary.sqlite3 + fallback.sqlite3 + definitions_pack.sqlite3 + db-assets.sha256"
}

main "$@"
