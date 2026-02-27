#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_VENV="${TRANSLATOR_BACKEND_VENV:-${ROOT_DIR}/.venv-desktop}"
HEALTHCHECK_MODE="${1:-}"
SESSION_ENV_WAIT_SECONDS="${TRANSLATOR_SESSION_ENV_WAIT_SECONDS:-30}"

import_systemd_session_environment() {
  command -v systemctl >/dev/null 2>&1 || return 0
  local line=""
  local key=""
  local value=""
  while IFS= read -r line; do
    key="${line%%=*}"
    value="${line#*=}"
    case "${key}" in
      DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS|XDG_CURRENT_DESKTOP|XAUTHORITY)
        if [[ -z "${!key:-}" && -n "${value}" ]]; then
          export "${key}=${value}"
        fi
        ;;
    esac
  done < <(systemctl --user show-environment 2>/dev/null || true)
}

wait_for_session_environment() {
  local deadline=$((SECONDS + SESSION_ENV_WAIT_SECONDS))
  while (( SECONDS < deadline )); do
    import_systemd_session_environment
    if [[ -n "${XDG_RUNTIME_DIR:-}" && ( -n "${WAYLAND_DISPLAY:-}" || -n "${DISPLAY:-}" ) ]]; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

prepare_runtime_environment() {
  if [[ -z "${XDG_CONFIG_HOME:-}" ]]; then
    export XDG_CONFIG_HOME="${HOME}/.config"
  fi
  wait_for_session_environment
}

validate_gtk_display() {
  "${DESKTOP_VENV}/bin/python" -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk, Gdk; Gtk.init(); import sys; sys.exit(0 if Gdk.Display.get_default() is not None else 1)" >/dev/null 2>&1
}

run_healthcheck() {
  if [[ ! -x "${DESKTOP_VENV}/bin/python" ]]; then
    echo "missing backend venv: ${DESKTOP_VENV}" >&2
    return 1
  fi
  if ! prepare_runtime_environment; then
    echo "session environment is not ready (DISPLAY/WAYLAND_DISPLAY/XDG_RUNTIME_DIR)" >&2
    return 1
  fi
  if ! "${DESKTOP_VENV}/bin/python" -c "import importlib; importlib.import_module('gi')" >/dev/null 2>&1
  then
    echo "backend venv is missing gi bindings" >&2
    return 1
  fi
  if ! validate_gtk_display; then
    echo "gtk display is not available yet" >&2
    return 1
  fi
  return 0
}

if [[ "${HEALTHCHECK_MODE}" == "--healthcheck" ]]; then
  run_healthcheck
  exit $?
fi

run_healthcheck
export PYTHONPATH="${ROOT_DIR}"
exec "${DESKTOP_VENV}/bin/python" -m desktop_app.main
