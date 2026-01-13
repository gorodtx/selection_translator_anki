from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import importlib

from desktop_app.application.history import HistoryItem
from desktop_app.ui.drag import attach_window_drag
from desktop_app.ui.theme import apply_theme
from desktop_app import gtk_types
from desktop_app import telemetry
from translate_logic.models import TranslationStatus

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gdk", "4.0")
    require_version("Gtk", "4.0")
Gdk = importlib.import_module("gi.repository.Gdk")
Gtk = importlib.import_module("gi.repository.Gtk")


class HistoryWindow:
    def __init__(
        self,
        *,
        app: gtk_types.Gtk.Application,
        on_close: Callable[[], None],
        on_settings: Callable[[], None],
        on_select: Callable[[HistoryItem], None],
    ) -> None:
        self._on_close_cb = on_close
        self._on_settings_cb = on_settings
        self._on_select_cb = on_select
        window = Gtk.ApplicationWindow(application=app)
        window.set_title("Translator")
        window.set_default_size(520, 360)
        window.set_resizable(True)
        window.set_hide_on_close(True)
        window.set_decorated(False)
        if hasattr(window, "set_gravity") and hasattr(Gdk, "Gravity"):
            window.set_gravity(Gdk.Gravity.CENTER)
        window.connect("close-request", self._handle_close_request)

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._handle_key_pressed)
        window.add_controller(controller)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)

        title = Gtk.Label(label="History")
        title.set_xalign(0.0)
        title.add_css_class("history-title")

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        if hasattr(list_box, "set_activate_on_single_click"):
            list_box.set_activate_on_single_click(True)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(list_box)

        settings_button = Gtk.Button(label="Settings")
        settings_button.connect("clicked", self._handle_settings_clicked)

        root.append(title)
        root.append(scroller)
        root.append(settings_button)

        attach_window_drag(window, root)
        window.set_child(root)
        apply_theme()

        self._window = window
        self._list_box = list_box
        self._items: list[HistoryItem] = []
        self._rows: list[_HistoryRow] = []
        telemetry.log_event("ui.history_window.created")

    @property
    def window(self) -> gtk_types.Gtk.ApplicationWindow:
        return self._window

    def present(self) -> None:
        telemetry.log_event("ui.history_window.present")
        self._window.present()

    def hide(self) -> None:
        telemetry.log_event("ui.history_window.hide")
        self._window.hide()

    def refresh(self, items: Iterable[HistoryItem]) -> None:
        filtered: list[HistoryItem] = []
        for item in items:
            if item.result.status is not TranslationStatus.SUCCESS:
                continue
            filtered.append(item)
        if len(filtered) == len(self._rows):
            self._items = filtered
            for row_data, item in zip(self._rows, filtered, strict=True):
                current = row_data.item
                _set_label_text(row_data.original, current.text, item.text)
                _set_label_text(
                    row_data.translation,
                    current.result.translation_ru.text,
                    item.result.translation_ru.text,
                )
                row_data.item = item
            return
        child = self._list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._list_box.remove(child)
            child = next_child
        self._items = filtered
        self._rows = []
        for item in filtered:
            row = Gtk.ListBoxRow()
            container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            original = Gtk.Label(label=item.text)
            original.set_xalign(0.0)
            original.set_wrap(True)
            original.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            original.set_max_width_chars(48)
            original.add_css_class("history-original")

            translation = Gtk.Label(label=item.result.translation_ru.text)
            translation.set_xalign(0.0)
            translation.set_wrap(True)
            translation.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            translation.set_max_width_chars(48)

            container.append(original)
            container.append(translation)
            row.set_child(container)
            row_data = _HistoryRow(
                row=row,
                original=original,
                translation=translation,
                item=item,
            )
            gesture = Gtk.GestureClick()
            gesture.connect("released", self._handle_row_click, row_data)
            row.add_controller(gesture)
            self._rows.append(row_data)
            self._list_box.append(row)

    def _handle_close_request(self, _window: object) -> bool:
        self._on_close_cb()
        return True

    def _handle_key_pressed(
        self, _controller: object, keyval: int, _keycode: int, _state: int
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._on_close_cb()
            return True
        return False

    def _handle_settings_clicked(self, _button: object) -> None:
        self._on_settings_cb()

    def _handle_row_click(
        self,
        _gesture: object,
        _n_press: int,
        _x: float,
        _y: float,
        row_data: "_HistoryRow",
    ) -> None:
        self._on_select_cb(row_data.item)
        if hasattr(self._list_box, "unselect_all"):
            self._list_box.unselect_all()


@dataclass(slots=True)
class _HistoryRow:
    row: gtk_types.Gtk.ListBoxRow
    original: gtk_types.Gtk.Label
    translation: gtk_types.Gtk.Label
    item: HistoryItem


def _set_label_text(label: gtk_types.Gtk.Label, current: str, value: str) -> None:
    if current != value:
        label.set_text(value)
