from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desktop_app.platform.paths import config_dir


def selection_cache_path() -> Path:
    return config_dir() / "last_selection.txt"


@dataclass(slots=True)
class SelectionCache:
    path: Path

    def read(self) -> str | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        return text

    def write(self, text: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(text, encoding="utf-8")
        except OSError:
            return

    def clear(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            return
