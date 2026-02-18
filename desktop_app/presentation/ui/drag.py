from __future__ import annotations

import importlib

from desktop_app import gtk_types

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gtk", "4.0")
Gtk = importlib.import_module("gi.repository.Gtk")


def attach_window_drag(
    window: gtk_types.Gtk.ApplicationWindow,
    widget: gtk_types.Gtk.Widget,
) -> None:
    gesture = Gtk.GestureDrag()
    gesture.set_button(1)

    def handle_drag_begin(
        gesture_obj: gtk_types.Gtk.GestureDrag, x: float, y: float
    ) -> None:
        _on_drag_begin(window, widget, gesture_obj, x, y)

    gesture.connect("drag-begin", handle_drag_begin)
    widget.add_controller(gesture)


def _on_drag_begin(
    window: gtk_types.Gtk.ApplicationWindow,
    widget: gtk_types.Gtk.Widget,
    gesture: gtk_types.Gtk.GestureDrag,
    x: float,
    y: float,
) -> None:
    if _is_interactive_target(widget, x, y):
        return
    surface = window.get_surface()
    if surface is None:
        return
    device = gesture.get_current_event_device()
    if device is None:
        return
    timestamp = gesture.get_current_event_time()
    button = gesture.get_current_button()
    if hasattr(surface, "begin_move"):
        surface.begin_move(device, button, x, y, timestamp)


def _is_interactive_target(widget: gtk_types.Gtk.Widget, x: float, y: float) -> bool:
    target = widget.pick(x, y, 0)
    while target is not None:
        if isinstance(
            target,
            (
                Gtk.Button,
                Gtk.Entry,
                Gtk.Label,
                Gtk.ListBox,
                Gtk.ListBoxRow,
            ),
        ):
            return True
        target = target.get_parent()
    return False
