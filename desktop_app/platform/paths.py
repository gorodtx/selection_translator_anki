from __future__ import annotations

import os
from pathlib import Path
import sys


def user_config_home() -> Path:
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata)
        return Path.home() / "AppData" / "Roaming"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_home:
        return Path(xdg_home)
    return Path.home() / ".config"


def runtime_state_home(namespace: str) -> Path:
    normalized = namespace.strip() or "translator"
    if sys.platform.startswith("win"):
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / normalized
    return user_config_home() / normalized
