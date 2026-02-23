#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXT_UUID="translator@com.translator.desktop"
DIST_DIR="${ROOT_DIR}/dev/dist/release"
ASSETS_DIR="${DIST_DIR}/assets"

OFFLINE_BASE_FILES=(
  "primary.sqlite3"
  "fallback.sqlite3"
  "definitions_pack.sqlite3"
)
ALLOW_DIRTY_RELEASE="${TRANSLATOR_RELEASE_ALLOW_DIRTY:-0}"
RELEASE_TAG="${TRANSLATOR_RELEASE_TAG:-}"

log() {
  echo "[release-build] $*"
}

fail() {
  echo "[release-build] $*" >&2
  exit 1
}

validate_release_tag() {
  if [[ -z "${RELEASE_TAG}" ]]; then
    return
  fi
  if [[ ! "${RELEASE_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]]; then
    fail "TRANSLATOR_RELEASE_TAG must match vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N"
  fi
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
    fail "tracked changes detected. Commit/stash before building release assets."
  fi
  if ! git -C "${ROOT_DIR}" diff --cached --quiet --ignore-submodules --; then
    fail "staged changes detected. Commit/stash before building release assets."
  fi
}

ensure_release_tag_is_new() {
  if [[ -z "${RELEASE_TAG}" ]]; then
    return
  fi
  if git -C "${ROOT_DIR}" rev-parse -q --verify "refs/tags/${RELEASE_TAG}" >/dev/null; then
    fail "release tag already exists locally: ${RELEASE_TAG} (immutable policy)"
  fi
  if git -C "${ROOT_DIR}" ls-remote --exit-code --tags origin "refs/tags/${RELEASE_TAG}" >/dev/null 2>&1; then
    fail "release tag already exists on origin: ${RELEASE_TAG} (immutable policy)"
  fi
}

sha256_of_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${file}" | awk '{print $1}'
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${file}" | awk '{print $1}'
    return
  fi
  python3 - "${file}" <<'PY'
import hashlib
import sys

path = sys.argv[1]
digest = hashlib.sha256()
with open(path, "rb") as file:
    for chunk in iter(lambda: file.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
}

resolve_local_base_path() {
  local filename="$1"
  local candidates=(
    "${ROOT_DIR}/translate_logic/infrastructure/language_base/offline_language_base/${filename}"
    "${ROOT_DIR}/translate_logic/language_base/offline_language_base/${filename}"
    "${ROOT_DIR}/offline_language_base/${filename}"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -s "${candidate}" ]]; then
      printf "%s" "${candidate}"
      return
    fi
  done
  printf ""
}

build_app_archive() {
  local app_archive="${ASSETS_DIR}/translator-app.tar.gz"
  rm -f "${app_archive}"
  (
    cd "${ROOT_DIR}"
    git archive --format=tar.gz --output "${app_archive}" HEAD \
      desktop_app \
      translate_logic \
      icons \
      scripts/runtime-requirements.txt
  )
  if tar -tzf "${app_archive}" | rg -q "\\.sqlite3$"; then
    fail "translator-app.tar.gz contains .sqlite3 files; release build aborted"
  fi
  log "built ${app_archive}"
}

build_extension_archive() {
  local ext_archive="${ASSETS_DIR}/translator-extension.zip"
  rm -f "${ext_archive}"
  python3 - "${ROOT_DIR}" "${ext_archive}" "${EXT_UUID}" <<'PY'
import pathlib
import sys
import zipfile

root = pathlib.Path(sys.argv[1])
archive = pathlib.Path(sys.argv[2])
uuid = sys.argv[3]
source = root / "gnome_extension" / uuid

with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(source.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root / "gnome_extension")
        zf.write(path, rel.as_posix())
PY
  log "built ${ext_archive}"
}

copy_offline_bases() {
  local filename
  for filename in "${OFFLINE_BASE_FILES[@]}"; do
    local src
    src="$(resolve_local_base_path "${filename}")"
    [[ -n "${src}" ]] || fail "offline base not found: ${filename}"
    cp "${src}" "${ASSETS_DIR}/${filename}"
    log "copied ${filename}"
  done
}

build_manifest() {
  local manifest="${ASSETS_DIR}/release-assets.sha256"
  : > "${manifest}"
  (
    cd "${ASSETS_DIR}"
    local filename
    for filename in \
      translator-app.tar.gz \
      translator-extension.zip \
      "${OFFLINE_BASE_FILES[@]}"; do
      [[ -s "${filename}" ]] || fail "missing asset file: ${filename}"
      printf "%s  %s\n" "$(sha256_of_file "${filename}")" "${filename}" >> "${manifest}"
    done
  )
  log "built ${manifest}"
}

main() {
  validate_release_tag
  ensure_clean_tracked_tree
  ensure_release_tag_is_new
  mkdir -p "${ASSETS_DIR}"

  build_app_archive
  build_extension_archive
  copy_offline_bases
  build_manifest

  cp "${ROOT_DIR}/scripts/install.sh" "${DIST_DIR}/install.sh"
  chmod +x "${DIST_DIR}/install.sh"

  log "release assets ready in ${DIST_DIR}"
  log "upload: assets/release-assets.sha256 + assets/*.tar.gz + assets/*.zip + assets/*.sqlite3 + install.sh"
}

main "$@"
