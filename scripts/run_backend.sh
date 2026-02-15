#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_VENV="${ROOT_DIR}/.venv-desktop"
HEALTHCHECK_MODE="${1:-}"

run_healthcheck() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to run backend" >&2
    return 1
  fi
  if [[ ! -x "${DESKTOP_VENV}/bin/python" ]]; then
    echo "missing desktop venv: ${DESKTOP_VENV}" >&2
    return 1
  fi
  if ! "${DESKTOP_VENV}/bin/python" - <<'PY' >/dev/null 2>&1
import importlib
importlib.import_module("gi")
PY
  then
    echo "desktop venv is missing gi bindings" >&2
    return 1
  fi
  return 0
}

ensure_desktop_venv() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to run backend" >&2
    exit 1
  fi

  if [[ ! -x "${DESKTOP_VENV}/bin/python" ]]; then
    (
      cd "${ROOT_DIR}"
      unset VIRTUAL_ENV
      UV_PROJECT_ENVIRONMENT="${DESKTOP_VENV}" \
        uv venv "${DESKTOP_VENV}" --python /usr/bin/python3 --system-site-packages
      UV_PROJECT_ENVIRONMENT="${DESKTOP_VENV}" \
        uv sync --python /usr/bin/python3
    )
    return
  fi

  if ! "${DESKTOP_VENV}/bin/python" - <<'PY' >/dev/null 2>&1
import importlib
importlib.import_module("gi")
PY
  then
    (
      cd "${ROOT_DIR}"
      unset VIRTUAL_ENV
      UV_PROJECT_ENVIRONMENT="${DESKTOP_VENV}" \
        uv venv "${DESKTOP_VENV}" --python /usr/bin/python3 --system-site-packages
      UV_PROJECT_ENVIRONMENT="${DESKTOP_VENV}" \
        uv sync --python /usr/bin/python3
    )
  fi
}

ensure_desktop_venv

if [[ "${HEALTHCHECK_MODE}" == "--healthcheck" ]]; then
  run_healthcheck
  exit $?
fi

export PYTHONPATH="${ROOT_DIR}"
exec "${DESKTOP_VENV}/bin/python" -m desktop_app.main
