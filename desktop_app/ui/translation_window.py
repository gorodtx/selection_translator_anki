from __future__ import annotations

from collections.abc import Callable
import importlib

from desktop_app.application.view_state import TranslationViewState
from desktop_app.notifications import BannerHost, Notification
from desktop_app.ui.drag import attach_window_drag
from desktop_app.ui.theme import apply_theme
from desktop_app import gtk_types
from translate_logic.highlight import build_highlight_spec, highlight_to_pango_markup

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

        self._label_translation = Gtk.Label(label="")
        self._label_translation.set_xalign(0.0)
        self._label_translation.set_wrap(True)
        self._label_translation.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_translation.set_max_width_chars(max_label_chars)
        self._label_translation.add_css_class("translation")

        self._label_definitions = Gtk.Label(label="")
        self._label_definitions.set_xalign(0.0)
        self._label_definitions.set_wrap(True)
        self._label_definitions.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_definitions.set_max_width_chars(max_label_chars)
        self._label_definitions.set_selectable(True)
        self._label_definitions.add_css_class("definition")

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

        self._row_translation = self._field_row(self._label_translation)
        self._sep_after_translation = Gtk.Separator(
            orientation=Gtk.Orientation.HORIZONTAL
        )
        self._row_definitions = self._field_row(self._label_definitions)
        self._row_examples = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._sep_before_actions = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)

        root.append(header)
        root.append(self._row_translation)
        root.append(self._sep_after_translation)
        root.append(self._row_definitions)
        root.append(self._row_examples)
        root.append(self._sep_before_actions)
        root.append(actions)

        attach_window_drag(window, root)
        window.set_child(root)
        apply_theme()

        self._window = window
        self._rendered_state: TranslationViewState | None = None
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

    def clear_banner(self) -> None:
        self._banner.clear()

    def _apply_state(self, state: TranslationViewState) -> None:
        previous = self._rendered_state
        if previous == state:
            return

        if previous is None or state.original != previous.original:
            self._label_original.set_text(state.original)
        if previous is None or state.translation != previous.translation:
            self._label_translation.set_text(state.translation)
        if (
            previous is None
            or state.definitions_items != previous.definitions_items
            or state.original_raw != previous.original_raw
        ):
            self._render_definitions(state)
        if (
            previous is None
            or state.examples != previous.examples
            or state.original_raw != previous.original_raw
        ):
            self._render_examples(state)

        if previous is None or state.loading != previous.loading:
            if state.loading:
                self._spinner.set_visible(True)
                self._spinner.start()
            else:
                self._spinner.stop()
                self._spinner.set_visible(False)
        header_visible = bool(state.original.strip()) or state.loading
        previous_header_visible = (
            None
            if previous is None
            else bool(previous.original.strip()) or previous.loading
        )
        if previous is None or header_visible != previous_header_visible:
            self._header_row.set_visible(header_visible)

        translation_visible = bool(state.translation.strip())
        definitions_visible = bool(state.definitions_items)
        examples_visible = bool(state.examples)
        previous_translation_visible = (
            None if previous is None else bool(previous.translation.strip())
        )
        previous_definitions_visible = (
            None if previous is None else bool(previous.definitions_items)
        )
        previous_examples_visible = None if previous is None else bool(previous.examples)

        if previous is None or translation_visible != previous_translation_visible:
            self._row_translation.set_visible(translation_visible)
        if previous is None or definitions_visible != previous_definitions_visible:
            self._row_definitions.set_visible(definitions_visible)
        if previous is None or examples_visible != previous_examples_visible:
            self._row_examples.set_visible(examples_visible)

        sep_after_translation_visible = translation_visible and (
            definitions_visible or examples_visible
        )
        previous_sep_after_translation_visible = (
            None
            if previous is None
            else bool(previous.translation.strip())
            and (bool(previous.definitions_items) or bool(previous.examples))
        )
        if (
            previous is None
            or sep_after_translation_visible != previous_sep_after_translation_visible
        ):
            self._sep_after_translation.set_visible(sep_after_translation_visible)

        sep_before_actions_visible = (
            translation_visible
            or definitions_visible
            or examples_visible
        )
        previous_sep_before_actions_visible = (
            None
            if previous is None
            else bool(previous.translation.strip())
            or bool(previous.definitions_items)
            or bool(previous.examples)
        )
        if (
            previous is None
            or sep_before_actions_visible != previous_sep_before_actions_visible
        ):
            self._sep_before_actions.set_visible(sep_before_actions_visible)

        if previous is None or state.can_add_anki != previous.can_add_anki:
            self._add_button.set_sensitive(state.can_add_anki)
        copy_all_sensitive = bool(state.translation.strip())
        previous_copy_all_sensitive = (
            None if previous is None else bool(previous.translation.strip())
        )
        if previous is None or copy_all_sensitive != previous_copy_all_sensitive:
            self._copy_all_button.set_sensitive(copy_all_sensitive)

        self._window.set_cursor(None)
        self._rendered_state = state

    def _field_row(self, label: gtk_types.Gtk.Label) -> gtk_types.Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label.set_xalign(0.0)
        row.append(label)
        return row

    def _render_examples(self, state: TranslationViewState) -> None:
        self._clear_children(self._row_examples)
        spec = build_highlight_spec(state.original_raw)
        for item in state.examples:
            example_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

            en_label = Gtk.Label(label="")
            en_label.set_xalign(0.0)
            en_label.set_wrap(True)
            en_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            en_label.set_max_width_chars(24)
            en_label.set_hexpand(True)
            en_label.set_selectable(True)
            en_label.add_css_class("example")
            en_label.set_markup(highlight_to_pango_markup(item.en, spec))

            example_box.append(en_label)
            self._row_examples.append(example_box)

    def _render_definitions(self, state: TranslationViewState) -> None:
        if not state.definitions_items:
            self._label_definitions.set_text("")
            return
        spec = build_highlight_spec(state.original_raw)
        lines: list[str] = []
        for index, definition in enumerate(state.definitions_items, start=1):
            rendered = highlight_to_pango_markup(definition, spec)
            lines.append(f"{index}. {rendered}")
        self._label_definitions.set_markup("\n".join(lines))

    def _clear_children(self, container: gtk_types.Gtk.Box) -> None:
        child = container.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            container.remove(child)
            child = next_child

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
