from __future__ import annotations

from collections.abc import Callable
import importlib

from desktop_app.application.view_state import TranslationViewState
from desktop_app.notifications import BannerHost, Notification
from desktop_app.ui.drag import attach_window_drag
from desktop_app.ui.theme import apply_theme
from desktop_app import gtk_types

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gdk", "4.0")
    require_version("Gtk", "4.0")
Gdk = importlib.import_module("gi.repository.Gdk")
Gtk = importlib.import_module("gi.repository.Gtk")


class TranslationWindow:
    def __init__(
        self,
        *,
        app: gtk_types.Gtk.Application,
        on_close: Callable[[], None],
        on_copy_all: Callable[[], None],
        on_add: Callable[[], None],
    ) -> None:
        self._on_close_cb = on_close
        self._on_copy_all = on_copy_all
        self._on_add = on_add
        max_label_chars = 24
        window = Gtk.ApplicationWindow(application=app)
        window.set_title("Translator")
        window.set_default_size(420, -1)
        window.set_resizable(False)
        window.set_hide_on_close(True)
        window.set_decorated(False)
        if hasattr(window, "set_gravity") and hasattr(Gdk, "Gravity"):
            window.set_gravity(Gdk.Gravity.CENTER)
        window.connect("close-request", self._handle_close_request)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._handle_key_pressed)
        window.add_controller(controller)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)
        self._banner = BannerHost()
        root.append(self._banner.widget)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._label_original = Gtk.Label(label="")
        self._label_original.set_xalign(0.0)
        self._label_original.set_wrap(True)
        self._label_original.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_original.set_max_width_chars(max_label_chars)
        self._label_original.set_hexpand(True)
        self._label_original.add_css_class("original")
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        header.append(self._label_original)
        header.append(self._spinner)
        self._header_row = header

        self._label_ipa = Gtk.Label(label="")
        self._label_ipa.set_xalign(0.0)
        self._label_ipa.set_wrap(True)
        self._label_ipa.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_ipa.set_max_width_chars(max_label_chars)
        self._label_ipa.add_css_class("ipa")

        self._label_translation = Gtk.Label(label="")
        self._label_translation.set_xalign(0.0)
        self._label_translation.set_wrap(True)
        self._label_translation.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_translation.set_max_width_chars(max_label_chars)
        self._label_translation.add_css_class("translation")

        self._label_example_en = Gtk.Label(label="")
        self._label_example_en.set_xalign(0.0)
        self._label_example_en.set_wrap(True)
        self._label_example_en.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_example_en.set_max_width_chars(max_label_chars)
        self._label_example_en.add_css_class("example")

        self._label_example_ru = Gtk.Label(label="")
        self._label_example_ru.set_xalign(0.0)
        self._label_example_ru.set_wrap(True)
        self._label_example_ru.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_example_ru.set_max_width_chars(max_label_chars)
        self._label_example_ru.add_css_class("example")

        self._add_button = Gtk.Button(label="Add to Anki")
        self._add_button.set_sensitive(False)
        self._add_button.connect("clicked", self._handle_add_clicked)

        self._copy_all_button = Gtk.Button(label="Copy All")
        self._copy_all_button.connect("clicked", self._handle_copy_all_clicked)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_hexpand(True)
        actions.set_homogeneous(True)
        self._copy_all_button.set_hexpand(True)
        self._add_button.set_hexpand(True)
        actions.append(self._copy_all_button)
        actions.append(self._add_button)

        self._row_ipa = self._field_row(self._label_ipa)
        self._sep_after_ipa = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._row_translation = self._field_row(self._label_translation)
        self._sep_after_translation = Gtk.Separator(
            orientation=Gtk.Orientation.HORIZONTAL
        )
        self._row_example_en = self._field_row(self._label_example_en)
        self._row_example_ru = self._field_row(self._label_example_ru)
        self._sep_before_actions = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)

        root.append(header)
        root.append(self._row_ipa)
        root.append(self._sep_after_ipa)
        root.append(self._row_translation)
        root.append(self._sep_after_translation)
        root.append(self._row_example_en)
        root.append(self._row_example_ru)
        root.append(self._sep_before_actions)
        root.append(actions)

        attach_window_drag(window, root)
        window.set_child(root)
        apply_theme()

        self._window = window
        self._apply_state(TranslationViewState.empty())

    @property
    def window(self) -> gtk_types.Gtk.ApplicationWindow:
        return self._window

    def present(self) -> None:
        self._window.present()

    def hide(self) -> None:
        self._window.hide()

    def apply_state(self, state: TranslationViewState) -> None:
        self._apply_state(state)

    def show_banner(self, notification: Notification) -> None:
        self._banner.notify(notification)

    def _apply_state(self, state: TranslationViewState) -> None:
        self._label_original.set_text(state.original)
        self._label_ipa.set_text(state.ipa)
        self._label_translation.set_text(state.translation)
        self._label_example_en.set_text(state.example_en)
        self._label_example_ru.set_text(state.example_ru)
        if state.loading:
            self._spinner.set_visible(True)
            self._spinner.start()
        else:
            self._spinner.stop()
            self._spinner.set_visible(False)
        header_visible = bool(state.original.strip()) or state.loading
        self._header_row.set_visible(header_visible)

        ipa_visible = bool(state.ipa.strip())
        translation_visible = bool(state.translation.strip())
        example_en_visible = bool(state.example_en.strip())
        example_ru_visible = bool(state.example_ru.strip())

        self._row_ipa.set_visible(ipa_visible)
        self._row_translation.set_visible(translation_visible)
        self._row_example_en.set_visible(example_en_visible)
        self._row_example_ru.set_visible(example_ru_visible)

        self._sep_after_ipa.set_visible(ipa_visible and translation_visible)
        self._sep_after_translation.set_visible(
            translation_visible and (example_en_visible or example_ru_visible)
        )
        self._sep_before_actions.set_visible(
            ipa_visible
            or translation_visible
            or example_en_visible
            or example_ru_visible
        )

        self._add_button.set_sensitive(state.can_add_anki)
        self._copy_all_button.set_sensitive(bool(state.translation.strip()))
        self._window.set_cursor(None)

    def _field_row(self, label: gtk_types.Gtk.Label) -> gtk_types.Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label.set_xalign(0.0)
        row.append(label)
        return row

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

    def _handle_add_clicked(self, _button: gtk_types.Gtk.Button) -> None:
        self._on_add()

    def _handle_copy_all_clicked(self, _button: gtk_types.Gtk.Button) -> None:
        self._on_copy_all()
