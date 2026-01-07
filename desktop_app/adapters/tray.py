from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys


@dataclass(slots=True)
class TrayManager:
    process: subprocess.Popen[bytes] | None = None

    def start(self, icon_path: Path) -> None:
        if not sys.platform.startswith("linux"):
            return
        if self.process is not None and self.process.poll() is None:
            return
        if not icon_path.exists():
            return
        root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        extra_path = str(root)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{extra_path}{os.pathsep}{existing}" if existing else extra_path
        )
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "desktop_app.tray_helper",
                    "--icon",
                    str(icon_path),
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            self.process = None

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self.process.terminate()
        except Exception:
            pass
        self.process = None
