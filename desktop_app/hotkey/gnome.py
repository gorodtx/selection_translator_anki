from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from desktop_app.hotkey import HotkeyBackend, HotkeyCallback, NotifyCallback

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_KEY = "custom-keybindings"
CUSTOM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
CUSTOM_PATH = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/translator/"
)


class GnomeHotkeyBackend(HotkeyBackend):
    def __init__(
        self,
        preferred_trigger: str,
        callback: HotkeyCallback,
        notify: NotifyCallback,
    ) -> None:
        super().__init__("gnome", preferred_trigger, callback, notify)
        self._installed = False

    def start(self) -> None:
        try:
            self._install_binding(self.preferred_trigger)
            self._installed = True
        except Exception as exc:
            self._notify("Translator", "Failed to register GNOME hotkey.")
            raise RuntimeError("GNOME hotkey registration failed") from exc

    def stop(self) -> None:
        return

    def _install_binding(self, trigger: str) -> None:
        command = _resolve_command()
        binding = _to_gnome_binding(trigger)
        if not command or not binding:
            raise RuntimeError("Missing hotkey command or binding.")
        bindings = _get_custom_bindings()
        if CUSTOM_PATH not in bindings:
            bindings.append(CUSTOM_PATH)
            _set_custom_bindings(bindings)
        _set_custom_value(CUSTOM_PATH, "name", "Translator")
        _set_custom_value(CUSTOM_PATH, "command", command)
        _set_custom_value(CUSTOM_PATH, "binding", binding)


def _resolve_command() -> str:
    bin_dir = Path(os.environ.get("XDG_BIN_HOME", Path.home() / ".local" / "bin"))
    wrapper = bin_dir / "translator"
    if wrapper.exists():
        return f"{wrapper} --translate"
    return f"{sys.executable} -m desktop_app.main --translate"


def _to_gnome_binding(trigger: str) -> str:
    parts = [part.strip() for part in trigger.split("+") if part.strip()]
    if not parts:
        return ""
    key = ""
    modifiers: list[str] = []
    for part in parts:
        name = part.casefold()
        if name in {"ctrl", "control"}:
            modifiers.append("<Control>")
        elif name == "shift":
            modifiers.append("<Shift>")
        elif name == "alt":
            modifiers.append("<Alt>")
        elif name in {"super", "meta"}:
            modifiers.append("<Super>")
        else:
            key = part
    if not key:
        return ""
    if len(key) == 1:
        key = key.lower()
    return "".join(modifiers) + key


def _get_custom_bindings() -> list[str]:
    output = _run(["gsettings", "get", SCHEMA, CUSTOM_KEY])
    text = output.strip()
    if text.startswith("@as "):
        text = text[4:]
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _set_custom_bindings(bindings: list[str]) -> None:
    _run(["gsettings", "set", SCHEMA, CUSTOM_KEY, _format_array(bindings)])


def _set_custom_value(path: str, key: str, value: str) -> None:
    target = f"{CUSTOM_SCHEMA}:{path}"
    _run(["gsettings", "set", target, key, _format_string(value)])


def _format_array(values: list[str]) -> str:
    items = ", ".join(f"'{item}'" for item in values)
    return f"[{items}]"


def _format_string(value: str) -> str:
    escaped = value.replace("'", "\\'")
    return f"'{escaped}'"


def _run(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gsettings failed")
    return result.stdout
