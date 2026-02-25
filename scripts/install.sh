#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-install}"

APP_ID="com.translator.desktop"
EXT_UUID="translator@com.translator.desktop"

SCRIPT_SOURCE="${BASH_SOURCE[0]-}"
if [[ -n "${SCRIPT_SOURCE}" && "${SCRIPT_SOURCE}" != "bash" && "${SCRIPT_SOURCE}" != "-bash" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")" && pwd)"
else
  SCRIPT_DIR="$(pwd)"
fi
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_ROOT="${HOME}/.local/share/translator"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
PREVIOUS_LINK="${APP_ROOT}/previous"
CACHE_DIR="${APP_ROOT}/cache"

EXT_DIR="${HOME}/.local/share/gnome-shell/extensions/${EXT_UUID}"
DBUS_DIR="${HOME}/.local/share/dbus-1/services"
DBUS_FILE="${DBUS_DIR}/${APP_ID}.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SYSTEMD_UNIT_FILE="${SYSTEMD_USER_DIR}/translator-desktop.service"

RELEASE_REPO="${TRANSLATOR_RELEASE_REPO:-gorodtx/selection_translator_anki}"
RELEASE_TAG="${TRANSLATOR_RELEASE_TAG:-}"
ASSETS_BASE_URL="${TRANSLATOR_ASSETS_BASE_URL:-}"
ASSETS_MANIFEST_ASSET="${TRANSLATOR_ASSETS_MANIFEST_ASSET:-release-assets.sha256}"
ASSETS_MANIFEST_URL="${TRANSLATOR_ASSETS_MANIFEST_URL:-}"
ASSETS_MANIFEST_PATH="${TRANSLATOR_ASSETS_MANIFEST_PATH:-}"
APP_ASSET="${TRANSLATOR_APP_ASSET:-translator-app.tar.gz}"
EXT_ASSET="${TRANSLATOR_EXTENSION_ASSET:-translator-extension.zip}"

FORCE_RELEASE_ASSETS="${TRANSLATOR_FORCE_RELEASE_ASSETS:-0}"
SKIP_HEALTHCHECK="${TRANSLATOR_SKIP_HEALTHCHECK:-0}"
INSTALL_MODE="${TRANSLATOR_INSTALL_MODE:-stable}"
ALLOW_LOCAL_SOURCE="${TRANSLATOR_ALLOW_LOCAL_SOURCE:-0}"

RUNTIME_REQUIREMENTS_FILE="${ROOT_DIR}/scripts/runtime-requirements.txt"

OFFLINE_BASE_FILES=(
  "primary.sqlite3"
  "fallback.sqlite3"
  "definitions_pack.sqlite3"
)

TMP_FILES=()

timestamp() {
  date +"%Y%m%d-%H%M%S"
}

log() {
  echo "[installer] $*" >&2
}

fail() {
  echo "[installer] $*" >&2
  exit 1
}

require_linux_host() {
  local uname_s
  uname_s="$(uname -s 2>/dev/null || echo unknown)"
  if [[ "${uname_s}" != "Linux" ]]; then
    fail "installer supports Linux hosts only (detected: ${uname_s})"
  fi
}

validate_install_mode() {
  case "${INSTALL_MODE}" in
    stable|dev)
      ;;
    *)
      fail "TRANSLATOR_INSTALL_MODE must be stable or dev (got: ${INSTALL_MODE})"
      ;;
  esac
  if [[ "${INSTALL_MODE}" == "stable" && "${ALLOW_LOCAL_SOURCE}" == "1" ]]; then
    fail "TRANSLATOR_ALLOW_LOCAL_SOURCE=1 is not allowed in stable mode"
  fi
}

local_source_allowed() {
  [[ "${INSTALL_MODE}" == "dev" && "${ALLOW_LOCAL_SOURCE}" == "1" ]]
}

cleanup_tmp_files() {
  local file
  for file in "${TMP_FILES[@]:-}"; do
    rm -f "${file}" "${file}.part" >/dev/null 2>&1 || true
  done
}

trap cleanup_tmp_files EXIT

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

safe_mktemp() {
  local file=""
  if file="$(mktemp 2>/dev/null)"; then
    printf "%s" "${file}"
    return
  fi
  mkdir -p "${CACHE_DIR}"
  if file="$(mktemp "${CACHE_DIR}/tmp.XXXXXX" 2>/dev/null)"; then
    printf "%s" "${file}"
    return
  fi
  fail "cannot create temporary file"
}

release_assets_base_url() {
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

manifest_download_url() {
  if [[ -n "${ASSETS_MANIFEST_URL}" ]]; then
    printf "%s" "${ASSETS_MANIFEST_URL}"
    return
  fi
  local base_url
  base_url="$(release_assets_base_url)"
  printf "%s/%s" "${base_url}" "${ASSETS_MANIFEST_ASSET}"
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
  if command -v python3 >/dev/null 2>&1; then
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
    return
  fi
  fail "sha256 tool not found (need sha256sum, shasum, or python3)"
}

download_file() {
  local url="$1"
  local dest="$2"
  local tmp="${dest}.part"

  mkdir -p "$(dirname "${dest}")"
  rm -f "${tmp}"

  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --retry 3 --connect-timeout 20 --output "${tmp}" "${url}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${tmp}" "${url}"
  else
    fail "curl/wget not found; cannot download ${url}"
  fi

  [[ -s "${tmp}" ]] || fail "downloaded file is empty: ${url}"
  mv "${tmp}" "${dest}"
}

manifest_checksum() {
  local manifest="$1"
  local filename="$2"
  awk -v target="${filename}" '
    BEGIN { found = 0 }
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

is_checksum_match() {
  local file="$1"
  local filename="$2"
  local manifest="$3"
  local expected
  expected="$(manifest_checksum "${manifest}" "${filename}" 2>/dev/null)" || return 1
  [[ "${expected}" =~ ^[0-9a-fA-F]{64}$ ]] || return 1
  local actual
  actual="$(sha256_of_file "${file}" 2>/dev/null)" || return 1
  [[ "${actual,,}" == "${expected,,}" ]]
}

require_checksum_match() {
  local file="$1"
  local filename="$2"
  local manifest="$3"
  local expected
  expected="$(manifest_checksum "${manifest}" "${filename}" 2>/dev/null)" || fail "manifest missing checksum for ${filename}"
  [[ "${expected}" =~ ^[0-9a-fA-F]{64}$ ]] || fail "invalid checksum format for ${filename} in manifest"
  local actual
  actual="$(sha256_of_file "${file}")"
  [[ "${actual,,}" == "${expected,,}" ]] || fail "checksum mismatch for ${filename}: expected ${expected}, got ${actual}"
}

has_local_source_tree() {
  [[ -d "${ROOT_DIR}/desktop_app" ]] || return 1
  [[ -d "${ROOT_DIR}/translate_logic" ]] || return 1
  [[ -d "${ROOT_DIR}/gnome_extension/${EXT_UUID}" ]] || return 1
  return 0
}

resolve_manifest_path() {
  if [[ -n "${ASSETS_MANIFEST_PATH}" ]]; then
    [[ -s "${ASSETS_MANIFEST_PATH}" ]] || fail "manifest not found: ${ASSETS_MANIFEST_PATH}"
    printf "%s" "${ASSETS_MANIFEST_PATH}"
    return
  fi

  local local_manifest="${ROOT_DIR}/scripts/release-assets.sha256"
  if [[ -s "${local_manifest}" ]] && has_local_source_tree && [[ "${FORCE_RELEASE_ASSETS}" != "1" ]] && local_source_allowed; then
    printf "%s" "${local_manifest}"
    return
  fi

  local manifest_url
  manifest_url="$(manifest_download_url)"
  local tmp_manifest
  tmp_manifest="$(safe_mktemp)" || fail "cannot create temporary file for manifest"
  TMP_FILES+=("${tmp_manifest}")
  download_file "${manifest_url}" "${tmp_manifest}"
  [[ -s "${tmp_manifest}" ]] || fail "downloaded manifest is empty: ${manifest_url}"
  printf "%s" "${tmp_manifest}"
}

asset_cache_path() {
  local filename="$1"
  mkdir -p "${CACHE_DIR}"
  printf "%s/%s" "${CACHE_DIR}" "${filename}"
}

ensure_asset_downloaded() {
  local filename="$1"
  local manifest="$2"

  local path
  path="$(asset_cache_path "${filename}")"
  if [[ -s "${path}" ]] && is_checksum_match "${path}" "${filename}" "${manifest}"; then
    printf "%s" "${path}"
    return
  fi

  local base_url
  base_url="$(release_assets_base_url)"
  local url="${base_url}/${filename}"
  log "downloading ${filename}"
  download_file "${url}" "${path}"
  require_checksum_match "${path}" "${filename}" "${manifest}"
  printf "%s" "${path}"
}

resolve_release_id() {
  if [[ -n "${TRANSLATOR_RELEASE_ID:-}" ]]; then
    printf "%s" "${TRANSLATOR_RELEASE_ID}"
    return
  fi
  if [[ -n "${RELEASE_TAG}" ]]; then
    printf "%s" "${RELEASE_TAG}"
    return
  fi
  printf "latest-%s" "$(timestamp)"
}

normalize_app_layout() {
  local app_dir="$1"
  [[ -d "${app_dir}" ]] || fail "app dir does not exist: ${app_dir}"

  if [[ -d "${app_dir}/desktop_app" && -d "${app_dir}/translate_logic" ]]; then
    return
  fi

  if [[ -d "${app_dir}/app/desktop_app" && -d "${app_dir}/app/translate_logic" ]]; then
    shopt -s dotglob
    mv "${app_dir}/app"/* "${app_dir}/"
    shopt -u dotglob
    rmdir "${app_dir}/app" >/dev/null 2>&1 || true
    return
  fi

  local first_dir
  first_dir="$(find "${app_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1 || true)"
  if [[ -n "${first_dir}" ]] && [[ -d "${first_dir}/desktop_app" ]] && [[ -d "${first_dir}/translate_logic" ]]; then
    shopt -s dotglob
    mv "${first_dir}"/* "${app_dir}/"
    shopt -u dotglob
    rmdir "${first_dir}" >/dev/null 2>&1 || true
    return
  fi

  fail "app bundle is missing desktop_app/translate_logic"
}

extract_tarball() {
  local archive="$1"
  local target_dir="$2"

  mkdir -p "${target_dir}"
  rm -rf "${target_dir}"/*

  if tar -xzf "${archive}" -C "${target_dir}" >/dev/null 2>&1; then
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "${archive}" "${target_dir}" <<'PY'
import pathlib
import tarfile
import sys

archive = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
with tarfile.open(archive, mode="r:*") as tar:
    tar.extractall(target)
PY
    return
  fi
  fail "cannot extract archive: ${archive}"
}

extract_extension_zip() {
  local archive="$1"
  local ext_dir="$2"
  local uuid="$3"

  python3 - "${archive}" "${ext_dir}" "${uuid}" <<'PY'
import pathlib
import shutil
import sys
import tempfile
import zipfile

archive = pathlib.Path(sys.argv[1])
ext_dir = pathlib.Path(sys.argv[2])
uuid = sys.argv[3]

work = pathlib.Path(tempfile.mkdtemp(prefix="translator-ext-"))
try:
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(work)

    candidate = work / uuid
    if not candidate.is_dir():
        top_dirs = [path for path in work.iterdir() if path.is_dir()]
        if len(top_dirs) == 1:
            candidate = top_dirs[0]
        else:
            candidate = work

    if ext_dir.exists():
        shutil.rmtree(ext_dir)
    ext_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(candidate, ext_dir)
finally:
    shutil.rmtree(work, ignore_errors=True)
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

install_offline_bases() {
  local app_dir="$1"
  local manifest="$2"

  local bases_dir="${app_dir}/translate_logic/infrastructure/language_base/offline_language_base"
  mkdir -p "${bases_dir}"

  local filename
  for filename in "${OFFLINE_BASE_FILES[@]}"; do
    local dst="${bases_dir}/${filename}"
    local local_src
    local_src="$(resolve_local_base_path "${filename}")"

    if local_source_allowed && [[ -n "${local_src}" ]] && is_checksum_match "${local_src}" "${filename}" "${manifest}"; then
      install -m 644 "${local_src}" "${dst}"
      require_checksum_match "${dst}" "${filename}" "${manifest}"
      log "offline base: ${filename} (local, verified)"
      continue
    fi

    local remote_src
    remote_src="$(ensure_asset_downloaded "${filename}" "${manifest}")"
    install -m 644 "${remote_src}" "${dst}"
    require_checksum_match "${dst}" "${filename}" "${manifest}"
    log "offline base: ${filename} (downloaded, verified)"
  done
}

prepare_runtime_requirements() {
  local output_file="$1"
  if [[ -s "${RUNTIME_REQUIREMENTS_FILE}" ]]; then
    cp "${RUNTIME_REQUIREMENTS_FILE}" "${output_file}"
    return
  fi
  cat > "${output_file}" <<'REQ'
aiohttp==3.13.2
REQ
}

ensure_release_venv() {
  local release_dir="$1"
  local venv_dir="${release_dir}/venv"
  if [[ ! -x "${venv_dir}/bin/python" ]]; then
    python3 -m venv --system-site-packages "${venv_dir}"
  fi

  local tmp_requirements
  tmp_requirements="$(safe_mktemp)" || fail "cannot create temporary file for requirements"
  TMP_FILES+=("${tmp_requirements}")
  prepare_runtime_requirements "${tmp_requirements}"

  "${venv_dir}/bin/python" -m pip --disable-pip-version-check install -r "${tmp_requirements}" >/dev/null
  "${venv_dir}/bin/python" - <<'PY'
import importlib
importlib.import_module("gi")
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

kept = [path for path in data if "com_translator_desktop" not in path and "translator" not in path]
if kept != list(data):
    subprocess.run(["gsettings", "set", SCHEMA, KEY, str(kept)], check=False)
PY
}

write_dbus_service() {
  mkdir -p "${DBUS_DIR}"
  cat > "${DBUS_FILE}" <<SERVICE
[D-BUS Service]
Name=${APP_ID}
SystemdService=translator-desktop.service
Exec=/usr/bin/systemctl --user start translator-desktop.service
SERVICE
  chmod 644 "${DBUS_FILE}"

  sync_user_session_environment

  if command -v gdbus >/dev/null 2>&1; then
    gdbus call --session \
      --dest org.freedesktop.DBus \
      --object-path /org/freedesktop/DBus \
      --method org.freedesktop.DBus.ReloadConfig >/dev/null 2>&1 || true
  fi
}

sync_user_session_environment() {
  local keys=(
    DISPLAY
    WAYLAND_DISPLAY
    XDG_RUNTIME_DIR
    DBUS_SESSION_BUS_ADDRESS
    XDG_CURRENT_DESKTOP
    XAUTHORITY
  )
  local names=()
  local pairs=()
  local key=""
  local value=""
  for key in "${keys[@]}"; do
    value="${!key:-}"
    if [[ -z "${value}" ]]; then
      continue
    fi
    names+=("${key}")
    pairs+=("${key}=${value}")
  done

  if [[ ${#names[@]} -gt 0 ]] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user import-environment "${names[@]}" >/dev/null 2>&1 || true
  fi

  if [[ ${#pairs[@]} -gt 0 ]] && command -v dbus-update-activation-environment >/dev/null 2>&1; then
    dbus-update-activation-environment --systemd "${pairs[@]}" >/dev/null 2>&1 || true
  fi
}

write_systemd_service() {
  mkdir -p "${SYSTEMD_USER_DIR}"

  local current_root="${CURRENT_LINK}"
  local current_app="${current_root}/app"
  local current_venv="${current_root}/venv"
  local memory_high="${TRANSLATOR_SYSTEMD_MEMORY_HIGH:-900M}"
  local memory_max="${TRANSLATOR_SYSTEMD_MEMORY_MAX:-1300M}"

  cat > "${SYSTEMD_UNIT_FILE}" <<SERVICE
[Unit]
Description=Translator desktop backend
After=graphical-session.target network.target
PartOf=graphical-session.target
StartLimitIntervalSec=0

[Service]
Type=dbus
BusName=${APP_ID}
WorkingDirectory=${current_app}
Environment=PYTHONPATH=${current_app}
Environment=XDG_CONFIG_HOME=%h/.config
Environment=TRANSLATOR_WARMUP_MODEL_ON_START=0
Environment=TRANSLATOR_OPUS_MT_INTER_THREADS=1
Environment=TRANSLATOR_OPUS_MT_INTRA_THREADS=3
ExecStartPre=${current_venv}/bin/python -c "import gi"
ExecStart=${current_venv}/bin/python -m desktop_app.main
Restart=on-failure
RestartSec=1
TimeoutStopSec=5
MemoryAccounting=yes
MemoryHigh=${memory_high}
MemoryMax=${memory_max}
OOMPolicy=kill

[Install]
WantedBy=graphical-session.target
SERVICE

  chmod 644 "${SYSTEMD_UNIT_FILE}"

  if command -v systemctl >/dev/null 2>&1; then
    sync_user_session_environment
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user enable translator-desktop.service >/dev/null 2>&1 || true
  fi
}

list_release_dirs_sorted() {
  python3 - "${RELEASES_DIR}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
if not root.is_dir():
    raise SystemExit(0)

items = [path for path in root.iterdir() if path.is_dir()]
items.sort(key=lambda path: path.stat().st_mtime, reverse=True)
for path in items:
    print(path)
PY
}

is_release_dir_path() {
  local path="$1"
  [[ -n "${path}" ]] || return 1
  [[ -d "${path}" ]] || return 1
  [[ "${path}" == "${RELEASES_DIR}"/* ]] || return 1
  return 0
}

ensure_previous_release_link() {
  local current_target=""
  if [[ -L "${CURRENT_LINK}" || -d "${CURRENT_LINK}" ]]; then
    current_target="$(readlink -f "${CURRENT_LINK}" || true)"
  fi

  local previous_target=""
  if [[ -L "${PREVIOUS_LINK}" || -d "${PREVIOUS_LINK}" ]]; then
    previous_target="$(readlink -f "${PREVIOUS_LINK}" || true)"
  fi

  if is_release_dir_path "${previous_target}" && [[ "${previous_target}" != "${current_target}" ]]; then
    return
  fi

  local candidate=""
  local release_dir=""
  while IFS= read -r release_dir; do
    [[ -n "${release_dir}" ]] || continue
    if [[ "${release_dir}" == "${current_target}" ]]; then
      continue
    fi
    candidate="${release_dir}"
    break
  done < <(list_release_dirs_sorted)

  if [[ -n "${candidate}" ]]; then
    ln -sfn "${candidate}" "${PREVIOUS_LINK}"
    return
  fi

  rm -f "${PREVIOUS_LINK}" >/dev/null 2>&1 || true
}

cleanup_old_releases() {
  ensure_previous_release_link

  local current_target=""
  if [[ -L "${CURRENT_LINK}" || -d "${CURRENT_LINK}" ]]; then
    current_target="$(readlink -f "${CURRENT_LINK}" || true)"
  fi

  local previous_target=""
  if [[ -L "${PREVIOUS_LINK}" || -d "${PREVIOUS_LINK}" ]]; then
    previous_target="$(readlink -f "${PREVIOUS_LINK}" || true)"
  fi

  local release_dir=""
  local removed=0
  while IFS= read -r release_dir; do
    [[ -n "${release_dir}" ]] || continue
    if [[ "${release_dir}" == "${current_target}" || "${release_dir}" == "${previous_target}" ]]; then
      continue
    fi
    rm -rf "${release_dir}"
    removed=$((removed + 1))
    log "pruned old release: $(basename "${release_dir}")"
  done < <(list_release_dirs_sorted)

  log "release cleanup: removed ${removed} old release(s)"
}

activate_release() {
  local release_dir="$1"

  local current_target=""
  if [[ -L "${CURRENT_LINK}" || -d "${CURRENT_LINK}" ]]; then
    current_target="$(readlink -f "${CURRENT_LINK}" || true)"
  fi

  if [[ -n "${current_target}" && "${current_target}" != "${release_dir}" && -d "${current_target}" ]]; then
    ln -sfn "${current_target}" "${PREVIOUS_LINK}"
  fi

  ln -sfn "${release_dir}" "${CURRENT_LINK}"
}

install_app_tree() {
  local release_dir="$1"
  local manifest="$2"

  local app_dir="${release_dir}/app"
  rm -rf "${app_dir}"
  mkdir -p "${app_dir}"

  if has_local_source_tree && [[ "${FORCE_RELEASE_ASSETS}" != "1" ]] && local_source_allowed; then
    copy_tree "${ROOT_DIR}/desktop_app" "${app_dir}/desktop_app"
    copy_tree "${ROOT_DIR}/translate_logic" "${app_dir}/translate_logic"
    copy_tree "${ROOT_DIR}/icons" "${app_dir}/icons"
    log "installed app from local repository"
    return
  fi

  local app_archive
  app_archive="$(ensure_asset_downloaded "${APP_ASSET}" "${manifest}")"
  extract_tarball "${app_archive}" "${app_dir}"
  normalize_app_layout "${app_dir}"
  log "installed app from release asset: ${APP_ASSET}"
}

install_extension_tree() {
  local manifest="$1"

  if has_local_source_tree && [[ "${FORCE_RELEASE_ASSETS}" != "1" ]] && local_source_allowed; then
    copy_tree "${ROOT_DIR}/gnome_extension/${EXT_UUID}" "${EXT_DIR}"
    log "installed extension from local repository"
  else
    local ext_archive
    ext_archive="$(ensure_asset_downloaded "${EXT_ASSET}" "${manifest}")"
    extract_extension_zip "${ext_archive}" "${EXT_DIR}" "${EXT_UUID}"
    log "installed extension from release asset: ${EXT_ASSET}"
  fi

  if command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas "${EXT_DIR}/schemas" >/dev/null 2>&1 || true
  fi

  clean_legacy_keybindings
  enable_extension
}

restart_runtime_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return
  fi
  sync_user_session_environment
  systemctl --user restart translator-desktop.service >/dev/null 2>&1 || true
}

wait_for_dbus_method() {
  local timeout_s="$1"
  local deadline
  deadline=$((SECONDS + timeout_s))

  while (( SECONDS < deadline )); do
    if gdbus introspect --session --dest "${APP_ID}" --object-path /com/translator/desktop 2>/dev/null | grep -q "com.translator.desktop"; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

run_dbus_healthcheck() {
  command -v gdbus >/dev/null 2>&1 || fail "gdbus not found; cannot run healthcheck"
  if command -v systemctl >/dev/null 2>&1; then
    sync_user_session_environment
    systemctl --user start translator-desktop.service >/dev/null 2>&1 || true
  fi

  if ! wait_for_dbus_method 20; then
    fail "D-Bus interface com.translator.desktop did not become ready"
  fi

  gdbus call --session --dest "${APP_ID}" --object-path /com/translator/desktop --method com.translator.desktop.Translate "hello" >/dev/null
  gdbus call --session --dest "${APP_ID}" --object-path /com/translator/desktop --method com.translator.desktop.Translate "look up" >/dev/null
  gdbus call --session --dest "${APP_ID}" --object-path /com/translator/desktop --method com.translator.desktop.GetAnkiStatus >/dev/null

  log "D-Bus smoke: Translate hello/look up + GetAnkiStatus passed"
}

install_or_update() {
  mkdir -p "${APP_ROOT}" "${RELEASES_DIR}" "${CACHE_DIR}"

  local manifest
  manifest="$(resolve_manifest_path)"
  log "checksum manifest: ${manifest}"

  local release_id
  release_id="$(resolve_release_id)"
  local release_dir="${RELEASES_DIR}/${release_id}"

  if [[ -d "${release_dir}" ]]; then
    rm -rf "${release_dir}"
  fi
  mkdir -p "${release_dir}"

  install_app_tree "${release_dir}" "${manifest}"
  install_offline_bases "${release_dir}/app" "${manifest}"
  ensure_release_venv "${release_dir}"
  activate_release "${release_dir}"

  install_extension_tree "${manifest}"
  write_systemd_service
  write_dbus_service
  restart_runtime_service

  if [[ "${SKIP_HEALTHCHECK}" != "1" ]]; then
    run_dbus_healthcheck
  fi

  cleanup_old_releases

  log "installed release: ${release_id}"
  log "current runtime: ${CURRENT_LINK}"
  log "extension: ${EXT_DIR}"
}

remove_all() {
  if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions disable "${EXT_UUID}" >/dev/null 2>&1 || true
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now translator-desktop.service >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi

  rm -rf "${EXT_DIR}" "${APP_ROOT}" "${DBUS_FILE}" "${SYSTEMD_UNIT_FILE}"
  clean_legacy_keybindings

  if command -v gdbus >/dev/null 2>&1; then
    gdbus call --session \
      --dest org.freedesktop.DBus \
      --object-path /org/freedesktop/DBus \
      --method org.freedesktop.DBus.ReloadConfig >/dev/null 2>&1 || true
  fi

  log "translator removed"
}

rollback_release() {
  [[ -L "${PREVIOUS_LINK}" ]] || fail "previous release is not available"
  local previous_target
  previous_target="$(readlink -f "${PREVIOUS_LINK}" || true)"
  [[ -n "${previous_target}" && -d "${previous_target}" ]] || fail "previous release target is invalid"

  local old_current=""
  if [[ -L "${CURRENT_LINK}" || -d "${CURRENT_LINK}" ]]; then
    old_current="$(readlink -f "${CURRENT_LINK}" || true)"
  fi

  ln -sfn "${previous_target}" "${CURRENT_LINK}"
  if [[ -n "${old_current}" && -d "${old_current}" ]]; then
    ln -sfn "${old_current}" "${PREVIOUS_LINK}"
  fi

  write_systemd_service
  write_dbus_service
  restart_runtime_service

  if [[ "${SKIP_HEALTHCHECK}" != "1" ]]; then
    run_dbus_healthcheck
  fi

  cleanup_old_releases

  log "rolled back to: ${previous_target}"
}

print_usage() {
  cat <<USAGE
Usage: $0 [install|update|remove|rollback|healthcheck]

Environment overrides:
  TRANSLATOR_RELEASE_REPO=owner/repo
  TRANSLATOR_RELEASE_TAG=vX.Y.Z
  TRANSLATOR_ASSETS_BASE_URL=https://.../download
  TRANSLATOR_ASSETS_MANIFEST_ASSET=release-assets.sha256
  TRANSLATOR_ASSETS_MANIFEST_URL=https://.../release-assets.sha256
  TRANSLATOR_ASSETS_MANIFEST_PATH=/path/to/release-assets.sha256
  TRANSLATOR_APP_ASSET=translator-app.tar.gz
  TRANSLATOR_EXTENSION_ASSET=translator-extension.zip
  TRANSLATOR_FORCE_RELEASE_ASSETS=1
  TRANSLATOR_SKIP_HEALTHCHECK=1
  TRANSLATOR_INSTALL_MODE=stable|dev
  TRANSLATOR_ALLOW_LOCAL_SOURCE=1   # only with TRANSLATOR_INSTALL_MODE=dev
USAGE
}

case "${ACTION}" in
  install|update)
    require_linux_host
    validate_install_mode
    install_or_update
    ;;
  remove)
    require_linux_host
    remove_all
    ;;
  rollback)
    require_linux_host
    validate_install_mode
    rollback_release
    ;;
  healthcheck)
    require_linux_host
    validate_install_mode
    run_dbus_healthcheck
    ;;
  *)
    print_usage
    exit 1
    ;;
esac
