from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys


@dataclass(slots=True)
class DesktopEntryManager:
    app_id: str

    def ensure_app_shortcut(self, icon_path: Path) -> None:
        if not sys.platform.startswith("linux"):
            return
        icon_installed = self._install_icon(icon_path)
        command = self._ensure_wrapper_script()
        root = Path(__file__).resolve().parents[2]
        shortcut_path = self._application_entry_path()
        try:
            shortcut_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        content = self._desktop_entry_content(
            command=command,
            root=root,
            autostart=False,
            icon_installed=icon_installed,
            icon_path=icon_path,
        )
        self._write_desktop_entry(shortcut_path, content)
        self._refresh_desktop_database(shortcut_path.parent)

    def ensure_autostart(self, icon_path: Path) -> None:
        command = self._ensure_wrapper_script()
        root = Path(__file__).resolve().parents[2]
        autostart_path = self.autostart_entry_path()
        legacy_autostart = Path.home() / ".config" / "autostart" / "translator.desktop"
        try:
            autostart_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        if legacy_autostart != autostart_path and legacy_autostart.exists():
            try:
                legacy_autostart.unlink()
            except OSError:
                pass
        content = self._desktop_entry_content(
            command=command,
            root=root,
            autostart=True,
            icon_installed=self._install_icon(icon_path),
            icon_path=icon_path,
        )
        try:
            autostart_path.write_text(content, encoding="utf-8")
        except OSError:
            return

    def autostart_entry_path(self) -> Path:
        return Path.home() / ".config" / "autostart" / f"{self.app_id}.desktop"

    def cleanup_desktop_entries(self) -> None:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        apps_dir = base / "applications"
        for name in ("translator.desktop", "com.translator.desktop.desktop"):
            path = apps_dir / name
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass

    def cleanup_desktop_cache(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        cache_dir = Path.home() / ".cache" / "gnome-shell"
        if not cache_dir.exists():
            return
        try:
            for entry in cache_dir.iterdir():
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                except OSError:
                    continue
        except OSError:
            return

    def _application_entry_path(self) -> Path:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return base / "applications" / f"{self.app_id}.desktop"

    def _icon_desktop_value(self, icon_installed: bool, icon_path: Path) -> str:
        if icon_installed:
            return self.app_id
        return str(icon_path)

    def _desktop_entry_content(
        self,
        *,
        command: str,
        root: Path,
        autostart: bool,
        icon_installed: bool,
        icon_path: Path,
    ) -> str:
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Translator",
            f"Exec={command}",
            f"Path={root}",
            "Terminal=false",
            "Categories=Utility;",
            f"StartupWMClass={self.app_id}",
            f"Icon={self._icon_desktop_value(icon_installed, icon_path)}",
            "NoDisplay=false",
            "Hidden=false",
        ]
        if autostart:
            lines.append("X-GNOME-Autostart-enabled=true")
        return "\n".join(lines)

    def _write_desktop_entry(self, path: Path, content: str) -> None:
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8")
            except OSError:
                existing = ""
            if existing == content:
                self._trust_desktop_entry(path)
                return
        try:
            path.write_text(content, encoding="utf-8")
        except OSError:
            return
        self._trust_desktop_entry(path)

    def _refresh_desktop_database(self, applications_dir: Path) -> None:
        cmd = shutil.which("update-desktop-database")
        if cmd is None:
            return
        try:
            subprocess.run(
                [cmd, str(applications_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return

    def _trust_desktop_entry(self, path: Path) -> None:
        try:
            path.chmod(0o755)
        except OSError:
            pass
        gio = shutil.which("gio")
        if gio is None:
            return
        try:
            subprocess.run(
                [gio, "set", str(path), "metadata::trusted", "yes"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return

    def _ensure_wrapper_script(self) -> str:
        root = Path(__file__).resolve().parents[2]
        bin_dir = Path(os.environ.get("XDG_BIN_HOME", Path.home() / ".local" / "bin"))
        uv_guess = bin_dir / "uv"
        uv_path = str(uv_guess) if uv_guess.exists() else (shutil.which("uv") or "")
        try:
            bin_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return f"{sys.executable} -m desktop_app.main"
        script_path = bin_dir / "translator"
        venv_python = root / ".venv" / "bin" / "python3"
        lines = [
            "#!/usr/bin/env sh",
            f'ROOT="{root}"',
            'cd "$ROOT" || exit 1',
            'PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"',
            f'UV_BIN="{uv_path}"',
            f'VENV_PY="{venv_python}"',
            'CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"',
            'UV_CACHE_DIR="${UV_CACHE_DIR:-$CACHE_HOME/translator/uv}"',
            'mkdir -p "$UV_CACHE_DIR" 2>/dev/null || true',
            "export UV_CACHE_DIR",
            'if [ -n "$TRANSLATOR_ACTION" ]; then',
            '  CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"',
            '  PID_FILE="$CONFIG_DIR/translator/app.pid"',
            '  if [ -f "$PID_FILE" ]; then',
            '    PID="$(cat "$PID_FILE" 2>/dev/null)"',
            '    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then',
            '      case "$TRANSLATOR_ACTION" in',
            '        translate) kill -s SIGUSR1 "$PID" 2>/dev/null && exit 0 ;;',
            '        settings) kill -s SIGUSR2 "$PID" 2>/dev/null && exit 0 ;;',
            '        history) kill -s SIGALRM "$PID" 2>/dev/null && exit 0 ;;',
            '        retry) kill -s SIGWINCH "$PID" 2>/dev/null && exit 0 ;;',
            "      esac",
            "    fi",
            "  fi",
            "fi",
            'if [ -x "$UV_BIN" ]; then',
            '  exec "$UV_BIN" run python -m desktop_app.main "$@"',
            "fi",
            'if [ -x "$VENV_PY" ]; then',
            '  exec "$VENV_PY" -m desktop_app.main "$@"',
            "fi",
            'exec python3 -m desktop_app.main "$@"',
            "",
        ]
        content = "\n".join(lines)
        try:
            if (
                not script_path.exists()
                or script_path.read_text(encoding="utf-8") != content
            ):
                script_path.write_text(content, encoding="utf-8")
        except OSError:
            return f"{sys.executable} -m desktop_app.main"
        try:
            script_path.chmod(0o755)
        except OSError:
            pass
        return str(script_path)

    def _install_icon(self, icon_path: Path) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        if not icon_path.exists():
            return False
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        icon_dir = base / "icons" / "hicolor" / "512x512" / "apps"
        try:
            icon_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        target = icon_dir / f"{self.app_id}.png"
        try:
            shutil.copy2(icon_path, target)
        except OSError:
            return False
        cmd = shutil.which("gtk-update-icon-cache")
        if cmd is None:
            return True
        try:
            subprocess.run(
                [cmd, str(base / "icons" / "hicolor")],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return True
        return True
