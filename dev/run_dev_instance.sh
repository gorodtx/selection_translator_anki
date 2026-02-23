#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-setup}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DEV_APP_ID="${TRANSLATOR_DEV_APP_ID:-com.translator.desktop.dev}"
DEV_DBUS_INTERFACE="${TRANSLATOR_DEV_DBUS_INTERFACE:-com.translator.desktop}"
DEV_DBUS_OBJECT_PATH="${TRANSLATOR_DEV_DBUS_OBJECT_PATH:-/com/translator/desktop}"
DEV_SYSTEMD_UNIT="${TRANSLATOR_DEV_SYSTEMD_UNIT:-translator-desktop-dev.service}"
DEV_RUNTIME_NAMESPACE="${TRANSLATOR_DEV_RUNTIME_NAMESPACE:-translator-dev}"
DEV_EXTENSION_UUID="${TRANSLATOR_DEV_EXTENSION_UUID:-translator-dev@com.translator.desktop}"
STABLE_SYSTEMD_UNIT="${TRANSLATOR_STABLE_SYSTEMD_UNIT:-translator-desktop.service}"
STABLE_EXTENSION_UUID="${TRANSLATOR_STABLE_EXTENSION_UUID:-translator@com.translator.desktop}"
STABLE_ROOT="${TRANSLATOR_STABLE_ROOT:-${HOME}/translator}"
DEV_BASES_SOURCE="${TRANSLATOR_DEV_BASES_SOURCE:-}"

DEV_ROOT="${TRANSLATOR_DEV_ROOT:-${HOME}/.local/share/translator-dev}"
DEV_RUNTIME_ROOT="${DEV_ROOT}/current"
DEV_APP_DIR="${DEV_RUNTIME_ROOT}/app"
DEV_VENV_DIR="${DEV_RUNTIME_ROOT}/venv"
DEV_DBUS_DIR="${HOME}/.local/share/dbus-1/services"
DEV_DBUS_FILE="${DEV_DBUS_DIR}/${DEV_APP_ID}.service"
DEV_SYSTEMD_DIR="${HOME}/.config/systemd/user"
DEV_SYSTEMD_FILE="${DEV_SYSTEMD_DIR}/${DEV_SYSTEMD_UNIT}"
DEV_EXTENSION_DIR="${HOME}/.local/share/gnome-shell/extensions/${DEV_EXTENSION_UUID}"
DEV_EXTENSION_BUILD_DIR="${ROOT_DIR}/dev/dist/dev/extension/${DEV_EXTENSION_UUID}"

DEV_XDG_CONFIG_HOME="${HOME}/.config/${DEV_RUNTIME_NAMESPACE}"
DEV_XDG_DATA_HOME="${HOME}/.local/share/${DEV_RUNTIME_NAMESPACE}/xdg-data"
DEV_XDG_CACHE_HOME="${HOME}/.cache/${DEV_RUNTIME_NAMESPACE}"
DEV_APP_BASES_DIR="${DEV_APP_DIR}/translate_logic/infrastructure/language_base/offline_language_base"

RUNTIME_REQUIREMENTS_FILE="${ROOT_DIR}/scripts/runtime-requirements.txt"
OFFLINE_BASE_FILES=(
  "primary.sqlite3"
  "fallback.sqlite3"
  "definitions_pack.sqlite3"
)

log() {
  echo "[dev-runtime] $*"
}

fail() {
  echo "[dev-runtime] $*" >&2
  exit 1
}

require_linux() {
  local uname_s
  uname_s="$(uname -s 2>/dev/null || echo unknown)"
  [[ "${uname_s}" == "Linux" ]] || fail "Linux host required (detected ${uname_s})"
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

prepare_runtime_tree() {
  mkdir -p "${DEV_APP_DIR}"
  copy_tree "${ROOT_DIR}/desktop_app" "${DEV_APP_DIR}/desktop_app"
  if command -v rsync >/dev/null 2>&1; then
    mkdir -p "${DEV_APP_DIR}/translate_logic"
    rsync -a --delete \
      --filter='P infrastructure/language_base/offline_language_base/*.sqlite3' \
      "${ROOT_DIR}/translate_logic/" "${DEV_APP_DIR}/translate_logic/"
  else
    copy_tree "${ROOT_DIR}/translate_logic" "${DEV_APP_DIR}/translate_logic"
  fi
  copy_tree "${ROOT_DIR}/icons" "${DEV_APP_DIR}/icons"
  mkdir -p "${DEV_APP_DIR}/scripts"
  cp "${ROOT_DIR}/scripts/runtime-requirements.txt" "${DEV_APP_DIR}/scripts/runtime-requirements.txt"
}

resolve_base_file() {
  local filename="$1"
  if [[ -n "${DEV_BASES_SOURCE}" && -s "${DEV_BASES_SOURCE}/${filename}" ]]; then
    printf "%s" "${DEV_BASES_SOURCE}/${filename}"
    return
  fi
  local candidates=(
    "${ROOT_DIR}/translate_logic/infrastructure/language_base/offline_language_base/${filename}"
    "${ROOT_DIR}/translate_logic/language_base/offline_language_base/${filename}"
    "${ROOT_DIR}/offline_language_base/${filename}"
    "${STABLE_ROOT}/translate_logic/infrastructure/language_base/offline_language_base/${filename}"
    "${STABLE_ROOT}/translate_logic/language_base/offline_language_base/${filename}"
    "${STABLE_ROOT}/offline_language_base/${filename}"
    "${HOME}/.local/share/translator/current/app/translate_logic/infrastructure/language_base/offline_language_base/${filename}"
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

sync_dev_offline_bases() {
  mkdir -p "${DEV_APP_BASES_DIR}"
  local filename src dst src_size dst_size
  for filename in "${OFFLINE_BASE_FILES[@]}"; do
    src="$(resolve_base_file "${filename}")"
    [[ -n "${src}" ]] || fail "offline base not found for dev: ${filename} (set TRANSLATOR_DEV_BASES_SOURCE=...)"
    dst="${DEV_APP_BASES_DIR}/${filename}"
    if [[ -s "${dst}" ]]; then
      src_size="$(stat -c '%s' "${src}")"
      dst_size="$(stat -c '%s' "${dst}")"
      if [[ "${src_size}" == "${dst_size}" ]]; then
        log "dev base already synced: ${filename}"
        continue
      fi
    fi
    cp --reflink=auto "${src}" "${dst}"
    [[ -s "${dst}" ]] || fail "failed to copy dev base: ${filename}"
    log "dev base synced: ${filename}"
  done
}

ensure_venv() {
  if [[ ! -x "${DEV_VENV_DIR}/bin/python" ]]; then
    python3 -m venv --system-site-packages "${DEV_VENV_DIR}"
  fi
  [[ -s "${RUNTIME_REQUIREMENTS_FILE}" ]] || fail "missing runtime requirements: ${RUNTIME_REQUIREMENTS_FILE}"
  "${DEV_VENV_DIR}/bin/python" -m pip --disable-pip-version-check install -r "${RUNTIME_REQUIREMENTS_FILE}" >/dev/null
  "${DEV_VENV_DIR}/bin/python" - <<'PY'
import importlib
importlib.import_module("gi")
PY
}

write_systemd_unit() {
  mkdir -p "${DEV_SYSTEMD_DIR}"
  mkdir -p "${DEV_XDG_CONFIG_HOME}" "${DEV_XDG_DATA_HOME}" "${DEV_XDG_CACHE_HOME}"

  cat > "${DEV_SYSTEMD_FILE}" <<SERVICE
[Unit]
Description=Translator desktop backend (dev)
After=graphical-session.target network.target
StartLimitIntervalSec=0

[Service]
Type=dbus
BusName=${DEV_APP_ID}
WorkingDirectory=${DEV_APP_DIR}
Environment=PYTHONPATH=${DEV_APP_DIR}
Environment=TRANSLATOR_APP_ID=${DEV_APP_ID}
Environment=TRANSLATOR_DBUS_INTERFACE=${DEV_DBUS_INTERFACE}
Environment=TRANSLATOR_DBUS_OBJECT_PATH=${DEV_DBUS_OBJECT_PATH}
Environment=TRANSLATOR_RUNTIME_NAMESPACE=${DEV_RUNTIME_NAMESPACE}
Environment=XDG_CONFIG_HOME=${DEV_XDG_CONFIG_HOME}
Environment=XDG_DATA_HOME=${DEV_XDG_DATA_HOME}
Environment=XDG_CACHE_HOME=${DEV_XDG_CACHE_HOME}
Environment=TRANSLATOR_WARMUP_MODEL_ON_START=0
Environment=TRANSLATOR_OPUS_MT_INTER_THREADS=1
Environment=TRANSLATOR_OPUS_MT_INTRA_THREADS=3
ExecStartPre=${DEV_VENV_DIR}/bin/python -c "import gi"
ExecStart=${DEV_VENV_DIR}/bin/python -m desktop_app.main
Restart=on-failure
RestartSec=1
TimeoutStopSec=5
MemoryAccounting=yes
MemoryHigh=700M
MemoryMax=1100M
OOMPolicy=kill

[Install]
WantedBy=default.target
SERVICE

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user enable "${DEV_SYSTEMD_UNIT}" >/dev/null 2>&1 || true
  fi
}

write_dbus_service() {
  mkdir -p "${DEV_DBUS_DIR}"
  cat > "${DEV_DBUS_FILE}" <<SERVICE
[D-BUS Service]
Name=${DEV_APP_ID}
SystemdService=${DEV_SYSTEMD_UNIT}
Exec=/usr/bin/systemctl --user start ${DEV_SYSTEMD_UNIT}
SERVICE
  chmod 644 "${DEV_DBUS_FILE}"

  if command -v gdbus >/dev/null 2>&1; then
    gdbus call --session \
      --dest org.freedesktop.DBus \
      --object-path /org/freedesktop/DBus \
      --method org.freedesktop.DBus.ReloadConfig >/dev/null 2>&1 || true
  fi
}

build_dev_extension() {
  "${ROOT_DIR}/dev/scripts/build_dev_extension.py" --root "${ROOT_DIR}" >/dev/null
}

install_dev_extension() {
  build_dev_extension
  copy_tree "${DEV_EXTENSION_BUILD_DIR}" "${DEV_EXTENSION_DIR}"
  if command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas "${DEV_EXTENSION_DIR}/schemas" >/dev/null 2>&1 || true
  fi
  if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions enable "${DEV_EXTENSION_UUID}" >/dev/null 2>&1 || true
  fi
  log "dev extension copied: ${DEV_EXTENSION_UUID} (if UUID is not visible yet, do logout/login once)"
}

uninstall_dev_extension() {
  if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions disable "${DEV_EXTENSION_UUID}" >/dev/null 2>&1 || true
  fi
  rm -rf "${DEV_EXTENSION_DIR}"
}

start_dev_service() {
  command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
  systemctl --user start "${DEV_SYSTEMD_UNIT}" >/dev/null
}

stop_dev_service() {
  command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
  systemctl --user stop "${DEV_SYSTEMD_UNIT}" >/dev/null 2>&1 || true
}

status_dev_service() {
  command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
  systemctl --user status "${DEV_SYSTEMD_UNIT}" --no-pager
}

wait_for_dbus() {
  local deadline=$((SECONDS + 20))
  while (( SECONDS < deadline )); do
    if gdbus introspect --session --dest "${DEV_APP_ID}" --object-path "${DEV_DBUS_OBJECT_PATH}" 2>/dev/null | grep -q "${DEV_DBUS_INTERFACE}"; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

call_with_retry() {
  local method="$1"
  local arg="${2:-}"
  local deadline=$((SECONDS + 15))
  while (( SECONDS < deadline )); do
    if [[ -n "${arg}" ]]; then
      if gdbus call --session --dest "${DEV_APP_ID}" --object-path "${DEV_DBUS_OBJECT_PATH}" --method "${method}" "${arg}" >/dev/null 2>&1; then
        return 0
      fi
    else
      if gdbus call --session --dest "${DEV_APP_ID}" --object-path "${DEV_DBUS_OBJECT_PATH}" --method "${method}" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 0.2
  done
  return 1
}

healthcheck() {
  command -v gdbus >/dev/null 2>&1 || fail "gdbus not found"
  start_dev_service
  wait_for_dbus || fail "dev D-Bus interface not ready"

  call_with_retry "${DEV_DBUS_INTERFACE}.Translate" "hello" || fail "dev translate(hello) failed"
  call_with_retry "${DEV_DBUS_INTERFACE}.Translate" "look up" || fail "dev translate(look up) failed"
  call_with_retry "${DEV_DBUS_INTERFACE}.GetAnkiStatus" || fail "dev GetAnkiStatus failed"

  log "healthcheck passed: ${DEV_APP_ID}"
}

setup() {
  require_linux
  prepare_runtime_tree
  sync_dev_offline_bases
  ensure_venv
  write_systemd_unit
  write_dbus_service
  install_dev_extension
  start_dev_service
  healthcheck
  log "dev runtime ready"
  log "unit=${DEV_SYSTEMD_UNIT} app_id=${DEV_APP_ID} extension=${DEV_EXTENSION_UUID}"
}

reload() {
  setup
}

switch_to_dev() {
  command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
  install_dev_extension
  if command -v gnome-extensions >/dev/null 2>&1; then
    if gnome-extensions list --user | grep -Fxq "${DEV_EXTENSION_UUID}"; then
      gnome-extensions disable "${STABLE_EXTENSION_UUID}" >/dev/null 2>&1 || true
      gnome-extensions enable "${DEV_EXTENSION_UUID}" >/dev/null 2>&1 || true
      log "gnome extension switched to dev uuid: ${DEV_EXTENSION_UUID}"
    else
      log "dev extension uuid not visible in current GNOME session; run logout/login once, then retry switch-to-dev"
    fi
  fi
  systemctl --user stop "${STABLE_SYSTEMD_UNIT}" >/dev/null 2>&1 || true
  start_dev_service
  healthcheck
}

switch_to_stable() {
  command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
  if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions disable "${DEV_EXTENSION_UUID}" >/dev/null 2>&1 || true
    gnome-extensions enable "${STABLE_EXTENSION_UUID}" >/dev/null 2>&1 || true
    log "gnome extension switched to stable uuid: ${STABLE_EXTENSION_UUID}"
  fi
  stop_dev_service
  systemctl --user start "${STABLE_SYSTEMD_UNIT}" >/dev/null 2>&1 || true
}

remove_all() {
  stop_dev_service
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable "${DEV_SYSTEMD_UNIT}" >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  rm -f "${DEV_SYSTEMD_FILE}" "${DEV_DBUS_FILE}"
  rm -rf "${DEV_ROOT}" "${DEV_XDG_CONFIG_HOME}" "${DEV_XDG_DATA_HOME}" "${DEV_XDG_CACHE_HOME}"
  uninstall_dev_extension
  log "dev runtime removed"
}

case "${ACTION}" in
  setup)
    setup
    ;;
  start)
    start_dev_service
    ;;
  stop)
    stop_dev_service
    ;;
  status)
    status_dev_service
    ;;
  healthcheck)
    healthcheck
    ;;
  sync-bases)
    sync_dev_offline_bases
    ;;
  switch-to-dev)
    switch_to_dev
    ;;
  switch-to-stable)
    switch_to_stable
    ;;
  install-extension)
    install_dev_extension
    ;;
  uninstall-extension)
    uninstall_dev_extension
    ;;
  reload)
    reload
    ;;
  remove)
    remove_all
    ;;
  *)
    cat <<USAGE
Usage: $0 [setup|start|stop|status|healthcheck|sync-bases|switch-to-dev|switch-to-stable|install-extension|uninstall-extension|reload|remove]

This script manages an isolated dev runtime namespace and must be run from dev worktree.
USAGE
    exit 1
    ;;
esac
