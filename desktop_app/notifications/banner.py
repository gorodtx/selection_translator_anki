from __future__ import annotations

from enum import Enum
import importlib

from desktop_app.notifications.models import Notification, NotificationLevel
from desktop_app import gtk_types

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("GLib", "2.0")
    require_version("Gtk", "4.0")
GLib = importlib.import_module("gi.repository.GLib")
Gtk = importlib.import_module("gi.repository.Gtk")


class BannerUi(Enum):
    TRANSITION_MS = 0


class BannerLayout(Enum):
    SPACING = 8


_LEVEL_CLASSES: dict[NotificationLevel, str] = {
    NotificationLevel.SUCCESS: "banner-success",
    NotificationLevel.INFO: "banner-info",
    NotificationLevel.WARNING: "banner-warning",
    NotificationLevel.ERROR: "banner-error",
}


class BannerHost:
    def __init__(self) -> None:
        self._label = Gtk.Label(label="")
        self._label.set_xalign(0.0)
        self._label.set_wrap(True)
        self._label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label.set_hexpand(True)

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=BannerLayout.SPACING.value,
        )
        box.add_css_class("banner")
        box.append(self._label)
        self._box = box

        revealer = Gtk.Revealer()
        revealer.set_reveal_child(False)
        revealer.set_transition_duration(BannerUi.TRANSITION_MS.value)
        revealer.set_child(box)
        self._revealer = revealer

    @property
    def widget(self) -> gtk_types.Gtk.Revealer:
        return self._revealer

    def notify(self, notification: Notification) -> None:
        GLib.idle_add(self._show_notification, notification)

    def _show_notification(self, notification: Notification) -> bool:
        self._apply_level(notification.level)
        self._label.set_text(notification.message)
        self._revealer.set_reveal_child(True)
        return False

    def _apply_level(self, level: NotificationLevel) -> None:
        for css_class in _LEVEL_CLASSES.values():
            self._box.remove_css_class(css_class)
        self._box.add_css_class(_LEVEL_CLASSES[level])
