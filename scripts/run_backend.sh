#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_VENV="${TRANSLATOR_BACKEND_VENV:-${ROOT_DIR}/.venv-desktop}"
HEALTHCHECK_MODE="${1:-}"

if [[ -z "${XDG_CONFIG_HOME:-}" ]]; then
  export XDG_CONFIG_HOME="${ROOT_DIR}/.config"
fi

run_healthcheck() {
  if [[ ! -x "${DESKTOP_VENV}/bin/python" ]]; then
    echo "missing backend venv: ${DESKTOP_VENV}" >&2
    return 1
  fi
  if ! "${DESKTOP_VENV}/bin/python" - <<'PY' >/dev/null 2>&1
import importlib
importlib.import_module("gi")
PY
  then
    echo "backend venv is missing gi bindings" >&2
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
