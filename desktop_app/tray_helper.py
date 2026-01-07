from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desktop_app.gtk3_types import Gtk
else:
    import gi

    gi.require_version("Gtk", "3.0")
    Gtk = importlib.import_module("gi.repository.Gtk")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--icon", required=True)
    parser.add_argument("--title", default="Translator")
    args = parser.parse_args()

    menu = Gtk.Menu()
    settings_item = Gtk.MenuItem(label="Settings")
    history_item = Gtk.MenuItem(label="History")
    quit_item = Gtk.MenuItem(label="Quit")
    settings_item.connect("activate", lambda *_: _activate_app("settings"))
    history_item.connect("activate", lambda *_: _activate_app("history"))
    quit_item.connect("activate", lambda *_: _quit_app())
    menu.append(settings_item)
    menu.append(history_item)
    menu.append(quit_item)
    menu.show_all()

    indicator = _maybe_create_indicator(args.icon, args.title, menu)
    if indicator is None:
        status_icon = Gtk.StatusIcon.new_from_file(args.icon)
        status_icon.set_visible(True)
        status_icon.set_tooltip_text(args.title)

        def on_popup(icon: object, button: int, event_time: int) -> None:
            menu.popup(
                None,
                None,
                Gtk.StatusIcon.position_menu,
                icon,
                button,
                event_time,
            )

        status_icon.connect("popup-menu", on_popup)
        status_icon.connect("activate", lambda *_: on_popup(status_icon, 0, 0))

    Gtk.main()


def _maybe_create_indicator(
    icon_path: str, title: str, menu: Gtk.Menu
) -> object | None:
    indicator_module = _try_import_indicator("AyatanaAppIndicator3")
    if indicator_module is None:
        indicator_module = _try_import_indicator("AppIndicator3")
    if indicator_module is None:
        return None
    indicator: object = indicator_module
    indicator_cls = getattr(indicator, "Indicator", None)
    category = getattr(indicator, "IndicatorCategory", None)
    status = getattr(indicator, "IndicatorStatus", None)
    if indicator_cls is None or category is None or status is None:
        return None
    app_indicator = indicator_cls.new(
        "translator",
        icon_path,
        category.APPLICATION_STATUS,
    )
    if hasattr(app_indicator, "set_title"):
        app_indicator.set_title(title)
    if hasattr(app_indicator, "set_icon_full"):
        app_indicator.set_icon_full(icon_path, title)
    app_indicator.set_status(status.ACTIVE)
    app_indicator.set_menu(menu)
    return app_indicator


def _try_import_indicator(module: str) -> object | None:
    try:
        gi = importlib.import_module("gi")
        gi.require_version(module, "0.1")
        return importlib.import_module(f"gi.repository.{module}")
    except Exception:
        return None


def _activate_app(action: str) -> None:
    signum = _signal_for_action(action)
    if signum is not None and _send_signal(signum):
        return
    subprocess.Popen([sys.executable, "-m", "desktop_app.main", f"--{action}"])
    time.sleep(0.4)
    if signum is not None:
        _send_signal(signum)


def _signal_for_action(action: str) -> int | None:
    if action == "settings":
        return signal.SIGUSR2
    if action == "history":
        return signal.SIGALRM
    if action == "retry":
        return getattr(signal, "SIGWINCH", signal.SIGINT)
    return None


def _send_signal(signum: int) -> bool:
    pid = _read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signum)
    except OSError:
        return False
    return True


def _quit_app() -> None:
    pid = _read_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    Gtk.main_quit()


def _read_pid() -> int | None:
    path = _pid_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    pid = int(raw)
    if pid <= 1:
        return None
    return pid


def _pid_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "translator" / "app.pid"


if __name__ == "__main__":
    main()
