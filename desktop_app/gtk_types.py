from __future__ import annotations

from typing import Callable


class Gtk:
    STYLE_PROVIDER_PRIORITY_APPLICATION: int

    class Application:
        def __init__(self, application_id: str | None = None, flags: int = 0) -> None:
            raise NotImplementedError

        def run(self, argv: list[str] | None = None) -> int:
            raise NotImplementedError

        def hold(self) -> None:
            raise NotImplementedError

        def release(self) -> None:
            raise NotImplementedError

        def send_notification(
            self, id: str | None, notification: Gio.Notification
        ) -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: object) -> None:
            raise NotImplementedError

        def do_startup(self) -> None:
            raise NotImplementedError

        def do_activate(self) -> None:
            raise NotImplementedError

        def get_active_window(self) -> Gtk.ApplicationWindow | None:
            raise NotImplementedError

        def get_dbus_connection(self) -> Gio.DBusConnection | None:
            raise NotImplementedError

    @staticmethod
    def accelerator_name(keyval: int, modifier_mask: int) -> str:
        raise NotImplementedError

    class Widget:
        def add_css_class(self, name: str) -> None:
            raise NotImplementedError

        def remove_css_class(self, name: str) -> None:
            raise NotImplementedError

        def set_hexpand(self, expand: bool) -> None:
            raise NotImplementedError

        def set_halign(self, align: int) -> None:
            raise NotImplementedError

        def set_visible(self, visible: bool) -> None:
            raise NotImplementedError

        def set_opacity(self, opacity: float) -> None:
            raise NotImplementedError

        def get_next_sibling(self) -> Gtk.Widget | None:
            raise NotImplementedError

        def add_controller(self, controller: object) -> None:
            raise NotImplementedError

        def set_cursor(self, cursor: Gdk.Cursor | None) -> None:
            raise NotImplementedError

        def pick(self, x: float, y: float, flags: int) -> Gtk.Widget | None:
            raise NotImplementedError

        def get_parent(self) -> Gtk.Widget | None:
            raise NotImplementedError

    class ApplicationWindow(Widget):
        def __init__(self, application: Gtk.Application | None = None) -> None:
            raise NotImplementedError

        def present(self) -> None:
            raise NotImplementedError

        def set_child(self, child: Gtk.Widget | None) -> None:
            raise NotImplementedError

        def set_title(self, title: str) -> None:
            raise NotImplementedError

        def set_decorated(self, setting: bool) -> None:
            raise NotImplementedError

        def set_resizable(self, setting: bool) -> None:
            raise NotImplementedError

        def set_default_size(self, width: int, height: int) -> None:
            raise NotImplementedError

        def set_hide_on_close(self, setting: bool) -> None:
            raise NotImplementedError

        def set_gravity(self, gravity: int) -> None:
            raise NotImplementedError

        def add_controller(self, controller: object) -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: object) -> None:
            raise NotImplementedError

        def close(self) -> None:
            raise NotImplementedError

        def hide(self) -> None:
            raise NotImplementedError

        def set_keep_above(self, setting: bool) -> None:
            raise NotImplementedError

        def get_surface(self) -> Gdk.Surface | None:
            raise NotImplementedError

    class Box(Widget):
        def __init__(self, orientation: int = 0, spacing: int = 0) -> None:
            raise NotImplementedError

        def append(self, child: Gtk.Widget) -> None:
            raise NotImplementedError

        def remove(self, child: Gtk.Widget) -> None:
            raise NotImplementedError

        def get_first_child(self) -> Gtk.Widget | None:
            raise NotImplementedError

        def set_margin_top(self, margin: int) -> None:
            raise NotImplementedError

        def set_margin_bottom(self, margin: int) -> None:
            raise NotImplementedError

        def set_margin_start(self, margin: int) -> None:
            raise NotImplementedError

        def set_margin_end(self, margin: int) -> None:
            raise NotImplementedError

        def set_spacing(self, spacing: int) -> None:
            raise NotImplementedError

        def set_hexpand(self, expand: bool) -> None:
            raise NotImplementedError

        def set_vexpand(self, expand: bool) -> None:
            raise NotImplementedError

        def set_halign(self, align: int) -> None:
            raise NotImplementedError

        def set_homogeneous(self, homogeneous: bool) -> None:
            raise NotImplementedError

    class Label(Widget):
        def __init__(self, label: str = "") -> None:
            raise NotImplementedError

        def set_markup(self, markup: str) -> None:
            raise NotImplementedError

        def set_text(self, text: str) -> None:
            raise NotImplementedError

        def set_wrap(self, wrap: bool) -> None:
            raise NotImplementedError

        def set_wrap_mode(self, mode: int) -> None:
            raise NotImplementedError

        def set_xalign(self, align: float) -> None:
            raise NotImplementedError

        def set_selectable(self, selectable: bool) -> None:
            raise NotImplementedError

        def add_css_class(self, name: str) -> None:
            raise NotImplementedError

        def set_hexpand(self, expand: bool) -> None:
            raise NotImplementedError

        def set_max_width_chars(self, n_chars: int) -> None:
            raise NotImplementedError

        def set_width_chars(self, n_chars: int) -> None:
            raise NotImplementedError

    class Entry(Widget):
        def __init__(self) -> None:
            raise NotImplementedError

        def set_text(self, text: str) -> None:
            raise NotImplementedError

        def get_text(self) -> str:
            raise NotImplementedError

        def set_hexpand(self, expand: bool) -> None:
            raise NotImplementedError

        def set_editable(self, editable: bool) -> None:
            raise NotImplementedError

        def set_width_chars(self, width: int) -> None:
            raise NotImplementedError

        def set_max_width_chars(self, width: int) -> None:
            raise NotImplementedError

        def set_alignment(self, alignment: float) -> None:
            raise NotImplementedError

    class Separator(Widget):
        def __init__(self, orientation: int = 0) -> None:
            raise NotImplementedError

    class Button(Widget):
        def __init__(self, label: str = "") -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: object) -> None:
            raise NotImplementedError

        def set_label(self, label: str) -> None:
            raise NotImplementedError

        def set_sensitive(self, sensitive: bool) -> None:
            raise NotImplementedError

        def set_visible(self, visible: bool) -> None:
            raise NotImplementedError

    class MessageDialog(Widget):
        def __init__(
            self,
            transient_for: Gtk.ApplicationWindow | None = None,
            modal: bool = False,
            buttons: int = 0,
            text: str = "",
        ) -> None:
            raise NotImplementedError

        def set_property(self, name: str, value: object) -> None:
            raise NotImplementedError

        def add_button(self, label: str, response_id: int) -> None:
            raise NotImplementedError

        def set_default_response(self, response_id: int) -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: object, *args: object) -> None:
            raise NotImplementedError

        def show(self) -> None:
            raise NotImplementedError

        def destroy(self) -> None:
            raise NotImplementedError

    class FileChooserNative:
        @staticmethod
        def new(
            title: str,
            parent: Gtk.ApplicationWindow | None,
            action: int,
            accept_label: str,
            cancel_label: str,
        ) -> Gtk.FileChooserNative:
            raise NotImplementedError

        def connect(self, name: str, callback: object) -> None:
            raise NotImplementedError

        def show(self) -> None:
            raise NotImplementedError

        def get_file(self) -> Gio.File | None:
            raise NotImplementedError

        def destroy(self) -> None:
            raise NotImplementedError

    class FileDialog:
        def __init__(self) -> None:
            raise NotImplementedError

        def set_title(self, title: str) -> None:
            raise NotImplementedError

        def open(
            self,
            parent: Gtk.ApplicationWindow | None,
            cancellable: object | None,
            callback: Callable[..., object],
            *args: object,
        ) -> None:
            raise NotImplementedError

        def open_finish(self, result: Gio.AsyncResult) -> Gio.File | None:
            raise NotImplementedError

    class CheckButton(Widget):
        def __init__(self, label: str = "") -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: object) -> None:
            raise NotImplementedError

        def get_active(self) -> bool:
            raise NotImplementedError

        def set_active(self, active: bool) -> None:
            raise NotImplementedError

        def set_label(self, label: str) -> None:
            raise NotImplementedError

    class Revealer(Widget):
        def __init__(self) -> None:
            raise NotImplementedError

        def set_child(self, child: Gtk.Widget | None) -> None:
            raise NotImplementedError

        def set_reveal_child(self, reveal: bool) -> None:
            raise NotImplementedError

        def get_reveal_child(self) -> bool:
            raise NotImplementedError

        def set_transition_duration(self, duration: int) -> None:
            raise NotImplementedError

    class Spinner(Widget):
        def __init__(self) -> None:
            raise NotImplementedError

        def start(self) -> None:
            raise NotImplementedError

        def stop(self) -> None:
            raise NotImplementedError

        def set_visible(self, visible: bool) -> None:
            raise NotImplementedError

        def set_spinning(self, spinning: bool) -> None:
            raise NotImplementedError

    class EventControllerKey:
        def __init__(self) -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: object) -> None:
            raise NotImplementedError

    class GestureDrag:
        def __init__(self) -> None:
            raise NotImplementedError

        def set_button(self, button: int) -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: object) -> None:
            raise NotImplementedError

        def get_current_event_device(self) -> object | None:
            raise NotImplementedError

        def get_current_event_time(self) -> int:
            raise NotImplementedError

        def get_current_button(self) -> int:
            raise NotImplementedError

    class CssProvider:
        def __init__(self) -> None:
            raise NotImplementedError

        def load_from_data(self, data: bytes) -> None:
            raise NotImplementedError

    class StyleContext:
        @staticmethod
        def add_provider_for_display(
            display: object, provider: Gtk.CssProvider, priority: int
        ) -> None:
            raise NotImplementedError

    class PickFlags:
        INSENSITIVE: int
        NON_TARGETABLE: int

    class DropDown(Widget):
        @staticmethod
        def new_from_strings(items: list[str]) -> Gtk.DropDown:
            raise NotImplementedError

        def get_selected(self) -> int:
            raise NotImplementedError

        def set_selected(self, position: int) -> None:
            raise NotImplementedError

    class ListBox(Widget):
        def __init__(self) -> None:
            raise NotImplementedError

        def append(self, child: Gtk.Widget) -> None:
            raise NotImplementedError

        def remove(self, child: Gtk.Widget) -> None:
            raise NotImplementedError

        def set_selection_mode(self, mode: int) -> None:
            raise NotImplementedError

        def get_first_child(self) -> Gtk.Widget | None:
            raise NotImplementedError

    class ListBoxRow(Widget):
        def __init__(self) -> None:
            raise NotImplementedError

        def set_child(self, child: Gtk.Widget | None) -> None:
            raise NotImplementedError

    class ScrolledWindow(Widget):
        def __init__(self) -> None:
            raise NotImplementedError

        def set_child(self, child: Gtk.Widget | None) -> None:
            raise NotImplementedError

        def set_vexpand(self, expand: bool) -> None:
            raise NotImplementedError

    class SelectionMode:
        NONE: int

    class Orientation:
        VERTICAL: int
        HORIZONTAL: int

    class Align:
        START: int
        END: int
        FILL: int
        CENTER: int

    class WrapMode:
        WORD_CHAR: int

    class FileChooserAction:
        OPEN: int

    class ButtonsType:
        NONE: int

    class ResponseType:
        ACCEPT: int
        OK: int
        CANCEL: int


class Gdk:
    class Cursor:
        @staticmethod
        def new_from_name(
            name: str, fallback: Gdk.Cursor | None = None
        ) -> Gdk.Cursor | None:
            raise NotImplementedError

    class Surface:
        def export_handle(
            self,
            callback: Callable[[object, str, object], None],
            user_data: object | None = None,
        ) -> bool:
            raise NotImplementedError

        def begin_move(
            self,
            device: object,
            button: int,
            x: float,
            y: float,
            timestamp: int,
        ) -> None:
            raise NotImplementedError

    class ContentProvider:
        @staticmethod
        def new_for_bytes(mime_type: str, bytes: GLib.Bytes) -> Gdk.ContentProvider:
            raise NotImplementedError

    class Display:
        @staticmethod
        def get_default() -> Gdk.Display | None:
            raise NotImplementedError

        def get_clipboard(self) -> Gdk.Clipboard:
            raise NotImplementedError

        def get_primary_clipboard(self) -> Gdk.Clipboard | None:
            raise NotImplementedError

        def get_name(self) -> str:
            raise NotImplementedError

    class Clipboard:
        def connect(self, name: str, callback: object) -> int:
            raise NotImplementedError

        def read_text_async(
            self,
            cancellable: object | None,
            callback: Callable[..., object],
            *args: object,
        ) -> None:
            raise NotImplementedError

        def read_text_finish(self, result: object) -> str | None:
            raise NotImplementedError

        def get_formats(self) -> Gdk.ContentFormats | None:
            raise NotImplementedError

        def set_content(self, provider: Gdk.ContentProvider) -> None:
            raise NotImplementedError

    class ContentFormats:
        def get_mime_types(self) -> list[str]:
            raise NotImplementedError

    class ModifierType:
        SHIFT_MASK: int
        CONTROL_MASK: int
        ALT_MASK: int
        SUPER_MASK: int
        META_MASK: int

    KEY_Escape: int

    @staticmethod
    def keyval_name(keyval: int) -> str | None:
        raise NotImplementedError

    @staticmethod
    def keyval_from_name(name: str) -> int:
        raise NotImplementedError

    class Gravity:
        CENTER: int


class Gio:
    class DBusConnection:
        def register_object(
            self,
            object_path: str,
            interface_info: object,
            method_call_closure: object | None = None,
            get_property_closure: object | None = None,
            set_property_closure: object | None = None,
        ) -> int:
            raise NotImplementedError

        def unregister_object(self, registration_id: int) -> None:
            raise NotImplementedError

    class DBusMethodInvocation:
        def return_value(self, value: object) -> None:
            raise NotImplementedError

    class BusType:
        SESSION: int

    class Notification:
        @staticmethod
        def new(title: str) -> Gio.Notification:
            raise NotImplementedError

        def set_body(self, body: str) -> None:
            raise NotImplementedError

    class File:
        def get_path(self) -> str | None:
            raise NotImplementedError

    class AsyncResult:
        pass

    @staticmethod
    def bus_get_sync(bus_type: int, cancellable: object | None) -> object:
        raise NotImplementedError


class GLib:
    class Variant:
        def __init__(self, signature: str, value: object) -> None:
            raise NotImplementedError

        def unpack(self) -> object:
            raise NotImplementedError

    class Bytes:
        @staticmethod
        def new(data: bytes) -> GLib.Bytes:
            raise NotImplementedError

    class MainContext:
        @staticmethod
        def default() -> GLib.MainContext:
            raise NotImplementedError

        def iteration(self, may_block: bool) -> bool:
            raise NotImplementedError

    @staticmethod
    def idle_add(function: Callable[..., bool], *args: object) -> int:
        raise NotImplementedError

    @staticmethod
    def timeout_add(interval: int, function: Callable[..., bool], *args: object) -> int:
        raise NotImplementedError

    @staticmethod
    def source_remove(tag: int) -> bool:
        raise NotImplementedError

    @staticmethod
    def set_application_name(name: str) -> None:
        raise NotImplementedError

    @staticmethod
    def set_prgname(name: str) -> None:
        raise NotImplementedError


class Gtk3:
    class StatusIcon:
        @staticmethod
        def new_from_file(filename: str) -> Gtk3.StatusIcon:
            raise NotImplementedError

        @staticmethod
        def position_menu(
            menu: Gtk3.Menu,
            x: int,
            y: int,
            push_in: bool,
            user_data: object | None,
        ) -> None:
            raise NotImplementedError

        def set_visible(self, visible: bool) -> None:
            raise NotImplementedError

        def set_tooltip_text(self, text: str) -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: Callable[..., object]) -> None:
            raise NotImplementedError

    class Menu:
        def __init__(self) -> None:
            raise NotImplementedError

        def append(self, child: Gtk3.MenuItem) -> None:
            raise NotImplementedError

        def show_all(self) -> None:
            raise NotImplementedError

        def popup_at_pointer(self, event: object | None) -> None:
            raise NotImplementedError

        def popup(
            self,
            parent_menu_shell: object | None,
            parent_menu_item: object | None,
            func: object | None,
            data: object | None,
            button: int,
            activate_time: int,
        ) -> None:
            raise NotImplementedError

    class MenuItem:
        def __init__(self, label: str = "") -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: Callable[..., object]) -> None:
            raise NotImplementedError

    @staticmethod
    def main() -> None:
        raise NotImplementedError

    @staticmethod
    def main_quit() -> None:
        raise NotImplementedError
