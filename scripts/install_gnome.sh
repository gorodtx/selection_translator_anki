#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-install}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT_UUID="translator@com.translator.desktop"
APP_ID="com.translator.desktop"

APP_ROOT="${HOME}/.local/share/translator"
APP_DIR="${APP_ROOT}/app"
EXT_DIR="${HOME}/.local/share/gnome-shell/extensions/${EXT_UUID}"
DBUS_DIR="${HOME}/.local/share/dbus-1/services"
DBUS_FILE="${DBUS_DIR}/${APP_ID}.service"
BASES_DIR="${APP_DIR}/translate_logic/language_base/offline_language_base"
LOCAL_MANIFEST_PATH="${ROOT_DIR}/scripts/release-assets.sha256"

RELEASE_REPO="${TRANSLATOR_RELEASE_REPO:-igor3204/selection_translator_anki}"
RELEASE_TAG="${TRANSLATOR_RELEASE_TAG:-}"
ASSETS_BASE_URL="${TRANSLATOR_ASSETS_BASE_URL:-}"
ASSETS_MANIFEST_ASSET="${TRANSLATOR_ASSETS_MANIFEST_ASSET:-release-assets.sha256}"
ASSETS_MANIFEST_URL="${TRANSLATOR_ASSETS_MANIFEST_URL:-}"
ASSETS_MANIFEST_PATH="${TRANSLATOR_ASSETS_MANIFEST_PATH:-}"

# Keep the installer deterministic: these files must exist after install.
OFFLINE_BASE_FILES=(
  "primary.sqlite3"
  "fallback.sqlite3"
  "definitions_pack.sqlite3"
)

_TMP_FILES=()

cleanup_tmp_files() {
  local file
  for file in "${_TMP_FILES[@]}"; do
    rm -f "${file}" "${file}.part" >/dev/null 2>&1 || true
  done
}

trap cleanup_tmp_files EXIT

fail() {
  echo "[installer] $*" >&2
  exit 1
}

copy_tree() {
  local src="$1"
  local dst="$2"
  [[ -d "${src}" ]] || fail "missing source directory: ${src}"
  if command -v rsync >/dev/null 2>&1; then
    mkdir -p "${dst}"
    rsync -a --delete "${src}/" "${dst}/"
    return
  fi
  rm -rf "${dst}"
  mkdir -p "${dst}"
  cp -a "${src}/." "${dst}/"
}

_release_assets_base_url() {
  if [[ -n "${ASSETS_BASE_URL}" ]]; then
    printf "%s" "${ASSETS_BASE_URL}"
    return
  fi
  if [[ -n "${RELEASE_TAG}" ]]; then
    printf "https://github.com/%s/releases/download/%s" "${RELEASE_REPO}" "${RELEASE_TAG}"
    return
  fi
  printf "https://github.com/%s/releases/latest/download" "${RELEASE_REPO}"
}

_manifest_download_url() {
  if [[ -n "${ASSETS_MANIFEST_URL}" ]]; then
    printf "%s" "${ASSETS_MANIFEST_URL}"
    return
  fi
  local base_url
  base_url="$(_release_assets_base_url)"
  printf "%s/%s" "${base_url}" "${ASSETS_MANIFEST_ASSET}"
}

_download_file() {
  local url="$1"
  local dest="$2"
  local tmp="${dest}.part"

  mkdir -p "$(dirname "${dest}")"
  rm -f "${tmp}"

  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --retry 3 --connect-timeout 15 --output "${tmp}" "${url}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${tmp}" "${url}"
  else
    fail "curl/wget not found; cannot download ${url}"
  fi

  [[ -s "${tmp}" ]] || fail "downloaded file is empty: ${url}"
  mv "${tmp}" "${dest}"
}

_resolve_manifest_path() {
  if [[ -n "${ASSETS_MANIFEST_PATH}" ]]; then
    [[ -s "${ASSETS_MANIFEST_PATH}" ]] || fail "manifest not found: ${ASSETS_MANIFEST_PATH}"
    printf "%s" "${ASSETS_MANIFEST_PATH}"
    return
  fi
  if [[ -s "${LOCAL_MANIFEST_PATH}" ]]; then
    printf "%s" "${LOCAL_MANIFEST_PATH}"
    return
  fi

  local manifest_url
  manifest_url="$(_manifest_download_url)"
  local tmp_manifest
  tmp_manifest="$(mktemp)"
  _TMP_FILES+=("${tmp_manifest}")
  _download_file "${manifest_url}" "${tmp_manifest}"
  [[ -s "${tmp_manifest}" ]] || fail "downloaded manifest is empty: ${manifest_url}"
  printf "%s" "${tmp_manifest}"
}

_manifest_checksum() {
  local manifest="$1"
  local filename="$2"
  awk -v target="${filename}" '
    BEGIN {
      found = 0
    }
    {
      sub(/\r$/, "", $0)
      if ($0 ~ /^[[:space:]]*#/ || $0 ~ /^[[:space:]]*$/) {
        next
      }
      checksum = $1
      file = $2
      sub(/^\*/, "", file)
      sub(/^\.\/+/, "", file)
      if (file == target) {
        print checksum
        found = 1
        exit
      }
    }
    END {
      if (found == 0) {
        exit 1
      }
    }
  ' "${manifest}"
}

_sha256_of_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${file}" | awk '{print $1}'
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${file}" | awk '{print $1}'
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "${file}" <<'PY'
import hashlib
import sys

path = sys.argv[1]
with open(path, "rb") as f:
    h = hashlib.sha256()
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
    return
  fi
  fail "sha256 tool not found (need sha256sum, shasum, or python3)"
}

_is_checksum_match() {
  local file="$1"
  local filename="$2"
  local manifest="$3"
  local expected
  expected="$(_manifest_checksum "${manifest}" "${filename}" 2>/dev/null)" || return 1
  [[ "${expected}" =~ ^[0-9a-fA-F]{64}$ ]] || return 1
  local actual
  actual="$(_sha256_of_file "${file}" 2>/dev/null)" || return 1
  [[ "${actual,,}" == "${expected,,}" ]]
}

_require_checksum_match() {
  local file="$1"
  local filename="$2"
  local manifest="$3"
  local expected
  expected="$(_manifest_checksum "${manifest}" "${filename}" 2>/dev/null)" || fail "manifest missing checksum for ${filename}"
  [[ "${expected}" =~ ^[0-9a-fA-F]{64}$ ]] || fail "invalid checksum format for ${filename} in manifest"
  local actual
  actual="$(_sha256_of_file "${file}")"
  [[ "${actual,,}" == "${expected,,}" ]] || fail "checksum mismatch for ${filename}: expected ${expected}, got ${actual}"
}

_local_base_path() {
  local filename="$1"
  local candidates=(
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

install_offline_bases() {
  local base_url
  base_url="$(_release_assets_base_url)"
  local manifest_path
  manifest_path="$(_resolve_manifest_path)"
  mkdir -p "${BASES_DIR}"
  echo "[installer] checksum manifest: ${manifest_path}"

  local filename
  for filename in "${OFFLINE_BASE_FILES[@]}"; do
    local dst="${BASES_DIR}/${filename}"
    local local_src
    local_src="$(_local_base_path "${filename}")"
    if [[ -n "${local_src}" ]]; then
      if ! _is_checksum_match "${local_src}" "${filename}" "${manifest_path}"; then
        echo "[installer] offline base: ${filename} (local checksum mismatch, downloading release asset)"
      else
        install -m 644 "${local_src}" "${dst}"
        _require_checksum_match "${dst}" "${filename}" "${manifest_path}"
        echo "[installer] offline base: ${filename} (local, verified)"
        continue
      fi
    fi

    local tmp_download="${dst}.download"
    rm -f "${tmp_download}" "${tmp_download}.part"
    _TMP_FILES+=("${tmp_download}")
    local url="${base_url}/${filename}"
    echo "[installer] offline base: ${filename} (download)"
    _download_file "${url}" "${tmp_download}"
    _require_checksum_match "${tmp_download}" "${filename}" "${manifest_path}"
    mv -f "${tmp_download}" "${dst}"
    _require_checksum_match "${dst}" "${filename}" "${manifest_path}"
    echo "[installer] offline base: ${filename} (verified)"
  done
}

clean_legacy_keybindings() {
  if ! command -v gsettings >/dev/null 2>&1; then
    return
  fi
  python3 - <<'PY'
import ast
import subprocess

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KEY = "custom-keybindings"

try:
    raw = subprocess.check_output(["gsettings", "get", SCHEMA, KEY], text=True).strip()
except Exception:
    raise SystemExit(0)

raw = raw.replace("@as ", "")
try:
    data = ast.literal_eval(raw)
except Exception:
    raise SystemExit(0)

if not isinstance(data, (list, tuple)):
    raise SystemExit(0)

kept: list[str] = []
for path in data:
    if "com_translator_desktop" in path or "translator" in path:
        continue
    kept.append(path)

if kept != list(data):
    subprocess.run(["gsettings", "set", SCHEMA, KEY, str(kept)], check=False)
PY
}

enable_extension() {
  if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.gnome.shell disable-user-extensions false >/dev/null 2>&1 || true
  fi
  if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions enable "${EXT_UUID}" >/dev/null 2>&1 || true
    return
  fi
  if command -v gsettings >/dev/null 2>&1; then
    python3 - <<'PY'
import ast
import subprocess

UUID = "translator@com.translator.desktop"


def _read_list(key: str) -> list[str]:
    try:
        raw = subprocess.check_output(["gsettings", "get", "org.gnome.shell", key], text=True).strip()
    except Exception:
        return []
    raw = raw.replace("@as ", "")
    try:
        data = ast.literal_eval(raw)
    except Exception:
        return []
    if isinstance(data, (list, tuple)):
        return list(data)
    return []


def _write_list(key: str, items: list[str]) -> None:
    subprocess.run(["gsettings", "set", "org.gnome.shell", key, str(items)], check=False)


enabled = _read_list("enabled-extensions")
if UUID not in enabled:
    enabled.append(UUID)
    _write_list("enabled-extensions", enabled)

disabled = _read_list("disabled-extensions")
if UUID in disabled:
    disabled = [item for item in disabled if item != UUID]
    _write_list("disabled-extensions", disabled)
PY
  fi
}

write_dbus_service() {
  mkdir -p "${DBUS_DIR}"
  cat > "${DBUS_FILE}" <<SERVICE
[D-BUS Service]
Name=${APP_ID}
Exec=/usr/bin/env PYTHONPATH=${APP_DIR} /usr/bin/python3 -m desktop_app.main
SERVICE
  chmod 644 "${DBUS_FILE}"
  if command -v gdbus >/dev/null 2>&1; then
    gdbus call --session \
      --dest org.freedesktop.DBus \
      --object-path /org/freedesktop/DBus \
      --method org.freedesktop.DBus.ReloadConfig >/dev/null 2>&1 || true
  fi
}

install_all() {
  copy_tree "${ROOT_DIR}/desktop_app" "${APP_DIR}/desktop_app"
  copy_tree "${ROOT_DIR}/translate_logic" "${APP_DIR}/translate_logic"
  copy_tree "${ROOT_DIR}/icons" "${APP_DIR}/icons"

  install_offline_bases

  copy_tree "${ROOT_DIR}/gnome_extension/${EXT_UUID}" "${EXT_DIR}"
  if command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas "${EXT_DIR}/schemas" >/dev/null 2>&1 || true
  fi

  write_dbus_service
  clean_legacy_keybindings
  enable_extension

  echo "Translator installed."
  echo "Installed app dir: ${APP_DIR}"
  echo "Installed offline bases: ${BASES_DIR}"
  echo "If extension does not appear, log out/in."
}

remove_all() {
  if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions disable "${EXT_UUID}" >/dev/null 2>&1 || true
  fi
  rm -rf "${EXT_DIR}" "${APP_ROOT}" "${DBUS_FILE}"
  clean_legacy_keybindings
  if command -v gdbus >/dev/null 2>&1; then
    gdbus call --session \
      --dest org.freedesktop.DBus \
      --object-path /org/freedesktop/DBus \
      --method org.freedesktop.DBus.ReloadConfig >/dev/null 2>&1 || true
  fi
  echo "Translator removed."
}

case "${ACTION}" in
  install|update)
    install_all
    ;;
  remove)
    remove_all
    ;;
  *)
    echo "Usage: $0 [install|update|remove]" >&2
    exit 1
    ;;
esac
