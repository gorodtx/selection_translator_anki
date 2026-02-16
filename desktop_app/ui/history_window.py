from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import importlib

from desktop_app.application.history import HistoryItem
from desktop_app.ui.drag import attach_window_drag
from desktop_app.ui.theme import apply_theme
from desktop_app import gtk_types
from translate_logic.highlight import build_highlight_spec, highlight_to_pango_markup
from translate_logic.models import Example, TranslationStatus

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
        on_select: Callable[[HistoryItem], None],
    ) -> None:
        self._on_close_cb = on_close
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

        root.append(title)
        root.append(scroller)

        attach_window_drag(window, root)
        window.set_child(root)
        apply_theme()

        self._window = window
        self._list_box = list_box
        self._items: list[HistoryItem] = []
        self._rows: list[_HistoryRow] = []
        self._render_signature: tuple[int, ...] | None = None

    @property
    def window(self) -> gtk_types.Gtk.ApplicationWindow:
        return self._window

    def present(self) -> None:
        self._window.present()

    def hide(self) -> None:
        self._window.hide()

    def refresh(self, items: Iterable[HistoryItem]) -> None:
        filtered: list[HistoryItem] = []
        for item in items:
            if item.result.status is not TranslationStatus.SUCCESS:
                continue
            filtered.append(item)
        signature = tuple(id(item) for item in filtered)
        if signature == self._render_signature:
            return
        self._clear_children(self._list_box)
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

            definition_text = _definition_preview(item)
            definition_spec = build_highlight_spec(item.text)
            definition = Gtk.Label(label="")
            definition.set_xalign(0.0)
            definition.set_wrap(True)
            definition.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            definition.set_max_width_chars(48)
            definition.set_selectable(True)
            definition.add_css_class("definition")
            definition.set_visible(bool(definition_text))
            if definition_text:
                definition.set_markup(
                    highlight_to_pango_markup(definition_text, definition_spec)
                )
            else:
                definition.set_text("")

            examples_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

            container.append(original)
            container.append(translation)
            container.append(definition)
            container.append(examples_row)
            row.set_child(container)
            row_data = _HistoryRow(
                row=row,
                original=original,
                translation=translation,
                definition=definition,
                examples=(),
                item=item,
            )
            row_data.examples = self._build_examples(
                examples_row=examples_row,
                examples=list(item.result.examples)[:3],
                query=item.text,
            )
            examples_row.set_visible(bool(row_data.examples))
            gesture = Gtk.GestureClick()
            gesture.connect("released", self._handle_row_click, row_data)
            row.add_controller(gesture)
            self._rows.append(row_data)
            self._list_box.append(row)
        self._render_signature = signature

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

    def _build_examples(
        self,
        *,
        examples_row: gtk_types.Gtk.Box,
        examples: list[Example],
        query: str,
    ) -> tuple["_HistoryExampleRow", ...]:
        built: list[_HistoryExampleRow] = []
        spec = build_highlight_spec(query)
        for example in examples:
            en = example.en.strip()
            if not en:
                continue
            example_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

            en_label = Gtk.Label(label="")
            en_label.set_xalign(0.0)
            en_label.set_wrap(True)
            en_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            en_label.set_max_width_chars(48)
            en_label.set_selectable(True)
            en_label.add_css_class("example")
            en_label.set_markup(highlight_to_pango_markup(en, spec))

            example_box.append(en_label)
            examples_row.append(example_box)
            built.append(
                _HistoryExampleRow(
                    en_label=en_label,
                )
            )
        return tuple(built)

    def _clear_children(self, container: gtk_types.Gtk.ListBox) -> None:
        child = container.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            container.remove(child)
            child = next_child


@dataclass(slots=True)
class _HistoryRow:
    row: gtk_types.Gtk.ListBoxRow
    original: gtk_types.Gtk.Label
    translation: gtk_types.Gtk.Label
    definition: gtk_types.Gtk.Label
    examples: tuple["_HistoryExampleRow", ...]
    item: HistoryItem


@dataclass(slots=True)
class _HistoryExampleRow:
    en_label: gtk_types.Gtk.Label


def _definition_preview(item: HistoryItem) -> str:
    definitions = item.result.definitions_en
    if not definitions:
        return ""
    return f"Definition EN: {definitions[0]}"
