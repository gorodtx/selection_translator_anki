#!/usr/bin/env bash
set -euo pipefail

EXT_UUID="translator@com.translator.desktop"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT_SRC="${ROOT_DIR}/gnome_extension/${EXT_UUID}"
EXT_DST="${HOME}/.local/share/gnome-shell/extensions/${EXT_UUID}"
DBUS_DIR="${HOME}/.local/share/dbus-1/services"
DBUS_FILE="${DBUS_DIR}/com.translator.desktop.service"
VENV_PY="${ROOT_DIR}/.venv/bin/python3"
if [[ -x "${VENV_PY}" ]]; then
  EXEC_CMD="${VENV_PY} -m desktop_app.main"
else
  EXEC_CMD="uv run python -m desktop_app.main"
fi

mkdir -p "${DBUS_DIR}"
cat > "${DBUS_FILE}" <<'EOF'
[D-BUS Service]
Name=com.translator.desktop
Exec=/usr/bin/env XDG_CONFIG_HOME=__ROOT_DIR__/.config PYTHONPATH=__ROOT_DIR__ __EXEC_CMD__
EOF
sed -i "s|__ROOT_DIR__|${ROOT_DIR}|g; s|__EXEC_CMD__|${EXEC_CMD}|g" "${DBUS_FILE}"
if command -v gdbus >/dev/null 2>&1; then
  gdbus call --session \
    --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.ReloadConfig >/dev/null 2>&1 || true
fi

mkdir -p "${EXT_DST}"
cp -a "${EXT_SRC}/." "${EXT_DST}/"
if command -v glib-compile-schemas >/dev/null 2>&1; then
  glib-compile-schemas "${EXT_DST}/schemas" >/dev/null 2>&1 || true
fi
if command -v gsettings >/dev/null 2>&1; then
  gsettings set org.gnome.shell disable-user-extensions false >/dev/null 2>&1 || true
  python - <<'PY'
import ast
import subprocess

UUID = "translator@com.translator.desktop"

def _read_list(key: str) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["gsettings", "get", "org.gnome.shell", key], text=True
        ).strip()
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
    subprocess.run(
        ["gsettings", "set", "org.gnome.shell", key, str(items)],
        check=False,
    )

enabled = _read_list("enabled-extensions")
if UUID not in enabled:
    enabled.append(UUID)
    _write_list("enabled-extensions", enabled)

disabled = _read_list("disabled-extensions")
if UUID in disabled:
    disabled = [item for item in disabled if item != UUID]
    _write_list("disabled-extensions", disabled)

def _read_custom_paths() -> list[str]:
    try:
        raw = subprocess.check_output(
            ["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"],
            text=True,
        ).strip()
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

def _custom_cmd(path: str) -> str:
    schema = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    try:
        return subprocess.check_output(
            ["gsettings", "get", f"{schema}:{path}", "command"], text=True
        ).strip().strip("'")
    except Exception:
        return ""

custom_paths = _read_custom_paths()
kept: list[str] = []
for path in custom_paths:
    cmd = _custom_cmd(path)
    if "translator" in cmd or "TRANSLATOR_ACTION" in cmd:
        continue
    kept.append(path)
if kept != custom_paths:
    _write_list("custom-keybindings", kept)
PY
else
  echo "gsettings not found; extension may need manual enabling" >&2
fi

if command -v pkill >/dev/null 2>&1; then
  pkill -f "desktop_app.main" >/dev/null 2>&1 || true
elif command -v pgrep >/dev/null 2>&1; then
  pids="$(pgrep -f "desktop_app.main" || true)"
  if [[ -n "${pids}" ]]; then
    kill ${pids} >/dev/null 2>&1 || true
  fi
fi

if command -v gdbus >/dev/null 2>&1; then
  gdbus call --session \
    --dest com.translator.desktop \
    --object-path /com/translator/desktop \
    --method com.translator.desktop.ShowSettings >/dev/null 2>&1 || true
else
  echo "gdbus not found; backend will start on next hotkey" >&2
fi

echo "Dev setup done."
