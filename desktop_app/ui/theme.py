from __future__ import annotations

import importlib

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gdk", "4.0")
    require_version("Gtk", "4.0")
Gdk = importlib.import_module("gi.repository.Gdk")
Gtk = importlib.import_module("gi.repository.Gtk")

_applied = False


def apply_theme() -> None:
    global _applied
    if _applied:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(
        b"""
        window { background-color: #2b2b2b; color: #e6e6e6; }
        label { color: #e6e6e6; }
        entry {
          background-color: #3a3a3a;
          color: #e6e6e6;
          border: 1px solid #4a4a4a;
          border-radius: 6px;
        }
        button {
          background-color: #3a3a3a;
          color: #e6e6e6;
          border: 1px solid #4a4a4a;
          border-radius: 8px;
          padding: 8px 12px;
        }
        button:hover { background-color: #444444; }
        separator { background-color: #444444; }
        .original { font-weight: 600; font-size: 1.05em; }
        .ipa { color: #b3b3b3; font-style: italic; }
        .translation { font-size: 1.1em; color: #e6e6e6; }
        .example { font-size: 1.1em; color: #e6e6e6; }
        .history-title { font-weight: 600; font-size: 1.1em; }
        .history-original { font-weight: 600; }
        .banner {
          padding: 6px 10px;
          border-radius: 8px;
          margin-bottom: 6px;
        }
        .banner-success { background-color: #2d5a3a; }
        .banner-info { background-color: #2d4b6a; }
        .banner-warning { background-color: #6a4b2d; }
        .banner-error { background-color: #6a2d2d; }
        """
    )
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    _applied = True
