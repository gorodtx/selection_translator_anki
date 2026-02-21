from __future__ import annotations

from collections.abc import Callable
import importlib
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote_plus
import webbrowser

from desktop_app.application.use_cases.anki_upsert import (
    AnkiFieldAction,
    AnkiImageAction,
    AnkiUpsertDecision,
    AnkiUpsertPreview,
)
from desktop_app.application.view_state import TranslationViewState
from desktop_app.infrastructure.notifications import BannerHost, Notification
from desktop_app.presentation.ui.drag import attach_window_drag
from desktop_app.presentation.ui.theme import apply_theme
from desktop_app import gtk_types
from translate_logic.shared.highlight import (
    build_highlight_spec,
    highlight_to_pango_markup,
)

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gdk", "4.0")
    require_version("Gio", "2.0")
    require_version("GLib", "2.0")
    require_version("Gtk", "4.0")
Gdk = importlib.import_module("gi.repository.Gdk")
Gio = importlib.import_module("gi.repository.Gio")
GLib = importlib.import_module("gi.repository.GLib")
Gtk = importlib.import_module("gi.repository.Gtk")


class TranslationWindow:
    _DEFAULT_WINDOW_WIDTH = 560
    _DEFAULT_WINDOW_HEIGHT = 210
    _MIN_WINDOW_HEIGHT = 140
    _MAX_WINDOW_WIDTH = 760
    _MAX_WINDOW_HEIGHT = 760
    _BASE_LABEL_CHARS = 52
    _IMAGE_MAX_BYTES = 5 * 1024 * 1024
    _IMAGE_AUTOCATCH_TIMEOUT_S = 60.0
    _IMAGE_MIN_AGE_S = 0.8
    _IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    _IMAGE_TEMP_SUFFIXES = (".part", ".crdownload", ".tmp")

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
        self._max_label_chars = self._BASE_LABEL_CHARS
        window = Gtk.ApplicationWindow(application=app)
        window.set_title("Translator")
        window.set_default_size(
            self._DEFAULT_WINDOW_WIDTH,
            self._DEFAULT_WINDOW_HEIGHT,
        )
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
        self._label_original.set_max_width_chars(self._max_label_chars)
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
        self._label_translation.set_max_width_chars(self._max_label_chars)
        self._label_translation.add_css_class("translation")

        self._label_definitions = Gtk.Label(label="")
        self._label_definitions.set_xalign(0.0)
        self._label_definitions.set_wrap(True)
        self._label_definitions.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_definitions.set_max_width_chars(self._max_label_chars)
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
        self._root = root
        window.set_child(root)
        apply_theme()

        self._window = window
        self._rendered_state: TranslationViewState | None = None
        self._upsert_popover: Any | None = None
        self._upsert_cleanup: Callable[[], None] | None = None
        self._last_target_size = (
            self._DEFAULT_WINDOW_WIDTH,
            self._DEFAULT_WINDOW_HEIGHT,
        )
        self._apply_state(TranslationViewState.empty())

    @property
    def window(self) -> gtk_types.Gtk.ApplicationWindow:
        return self._window

    def present(self) -> None:
        if hasattr(self._window, "unminimize"):
            try:
                self._window.unminimize()
            except Exception:
                pass
        if hasattr(self._window, "set_visible"):
            try:
                self._window.set_visible(True)
            except Exception:
                pass
        self._window.present()
        if hasattr(self._window, "grab_focus"):
            try:
                self._window.grab_focus()
            except Exception:
                pass

    def hide(self) -> None:
        self.hide_anki_upsert()
        self._window.hide()

    def apply_state(self, state: TranslationViewState) -> None:
        self._apply_state(state)

    def show_banner(self, notification: Notification) -> None:
        self._banner.notify(notification)

    def clear_banner(self) -> None:
        self._banner.clear()

    def show_anki_upsert(
        self,
        query_text: str,
        preview: AnkiUpsertPreview,
        on_apply: Callable[[AnkiUpsertDecision], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self.hide_anki_upsert()
        popover = Gtk.Popover()
        if hasattr(popover, "set_has_arrow"):
            popover.set_has_arrow(True)
        if hasattr(popover, "set_autohide"):
            popover.set_autohide(False)
        if hasattr(popover, "set_position") and hasattr(Gtk, "PositionType"):
            popover.set_position(Gtk.PositionType.TOP)
        if hasattr(popover, "set_offset"):
            popover.set_offset(0, -6)
        if hasattr(popover, "set_parent"):
            popover.set_parent(self._add_button)
        elif hasattr(popover, "set_relative_to"):
            popover.set_relative_to(self._add_button)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(8)
        content.set_margin_end(8)
        content.set_size_request(520, -1)

        title = Gtk.Label(label="Anki upsert")
        title.set_xalign(0.0)
        content.append(title)

        create_new_check = Gtk.CheckButton(label="Create new card")
        create_new_check.set_active(not bool(preview.matches))
        content.append(create_new_check)

        note_checks: list[tuple[int, gtk_types.Gtk.CheckButton]] = []
        if preview.matches:
            notes_title = Gtk.Label(label="Existing cards:")
            notes_title.set_xalign(0.0)
            content.append(notes_title)
            for index, match in enumerate(preview.matches):
                label = f"#{match.note_id} | {self._shorten(match.word)}"
                check = Gtk.CheckButton(label=label)
                check.set_active(index == 0)
                note_checks.append((match.note_id, check))
                content.append(check)

        translation_combo = self._build_action_combo()
        definitions_combo = self._build_action_combo()
        examples_combo = self._build_action_combo()
        image_combo = self._build_image_action_combo()

        content.append(self._labeled_row("Translation action:", translation_combo))
        content.append(self._labeled_row("Definitions action:", definitions_combo))
        content.append(self._labeled_row("Examples action:", examples_combo))
        content.append(self._labeled_row("Image action:", image_combo))

        translation_checks = self._build_value_checks(
            title="Translations:",
            values=preview.values.translations,
            parent=content,
        )
        definition_checks = self._build_value_checks(
            title="Definitions:",
            values=preview.values.definitions_en,
            parent=content,
        )
        example_checks = self._build_value_checks(
            title="Examples:",
            values=preview.values.examples_en,
            parent=content,
        )

        image_title = Gtk.Label(label="Image:")
        image_title.set_xalign(0.0)
        content.append(image_title)

        image_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        find_image_button = Gtk.Button(label="Find Image")
        select_image_button = Gtk.Button(label="Select File")
        clear_image_button = Gtk.Button(label="Clear")
        image_controls.append(find_image_button)
        image_controls.append(select_image_button)
        image_controls.append(clear_image_button)
        content.append(image_controls)

        image_status = Gtk.Label(label="No image selected.")
        image_status.set_xalign(0.0)
        image_status.set_wrap(True)
        image_status.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        content.append(image_status)

        preview_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        preview_picture: object | None = None
        picture_cls = getattr(Gtk, "Picture", None)
        if picture_cls is not None:
            try:
                preview_picture = picture_cls()
                if hasattr(preview_picture, "set_size_request"):
                    preview_picture.set_size_request(240, 140)
                if hasattr(preview_picture, "set_content_fit") and hasattr(
                    Gtk, "ContentFit"
                ):
                    preview_picture.set_content_fit(Gtk.ContentFit.COVER)
                preview_wrap.append(preview_picture)
            except Exception:
                preview_picture = None
        if preview_picture is None:
            no_preview = Gtk.Label(label="Image preview is unavailable.")
            no_preview.set_xalign(0.0)
            preview_wrap.append(no_preview)
        content.append(preview_wrap)

        selected_image_path: str | None = preview.values.image_path
        autocatch_started_at = 0.0
        downloads_monitor: Any | None = None
        downloads_monitor_handler: int | None = None
        downloads_dir = self._downloads_dir()

        def _stop_autocatch() -> None:
            nonlocal downloads_monitor, downloads_monitor_handler
            if downloads_monitor is None:
                return
            try:
                if downloads_monitor_handler is not None:
                    disconnect = getattr(downloads_monitor, "disconnect", None)
                    if callable(disconnect):
                        disconnect(downloads_monitor_handler)
            except Exception:
                pass
            try:
                cancel = getattr(downloads_monitor, "cancel", None)
                if callable(cancel):
                    cancel()
            except Exception:
                pass
            downloads_monitor = None
            downloads_monitor_handler = None

        def _set_preview(path: str | None, message: str) -> None:
            nonlocal selected_image_path
            selected_image_path = path
            image_status.set_text(message)
            if preview_picture is None:
                return
            try:
                if hasattr(preview_picture, "set_filename"):
                    preview_picture.set_filename(path or "")
            except Exception:
                pass

        if selected_image_path:
            _set_preview(
                selected_image_path,
                f"Selected: {Path(selected_image_path).name}",
            )

        def _capture_download_candidate() -> bool:
            candidate = self._first_download_candidate(
                downloads_dir,
                autocatch_started_at,
            )
            if candidate is None:
                return False
            ok, error_message = self._validate_image_path(
                candidate,
                min_age_s=self._IMAGE_MIN_AGE_S,
            )
            if not ok:
                if error_message == "too_recent":
                    return False
                return False
            _set_preview(str(candidate), f"Auto-selected: {candidate.name}")
            _stop_autocatch()
            return True

        def _on_downloads_changed(
            _monitor: Any,
            _file: Any,
            _other_file: Any,
            _event_type: Any,
        ) -> None:
            _capture_download_candidate()

        def _on_find_image(_button: object) -> None:
            nonlocal autocatch_started_at, downloads_monitor, downloads_monitor_handler
            normalized_query = " ".join(query_text.split())
            if not normalized_query:
                image_status.set_text("Empty query text.")
                return
            search_url = (
                "https://duckduckgo.com/?q="
                f"{quote_plus(normalized_query)}&iax=images&ia=images"
            )
            try:
                webbrowser.open(search_url)
            except Exception:
                image_status.set_text("Failed to open browser.")
                return
            _stop_autocatch()
            autocatch_started_at = time.time()
            if _capture_download_candidate():
                return

            try:
                directory = Gio.File.new_for_path(str(downloads_dir))
                flags = getattr(getattr(Gio, "FileMonitorFlags", None), "NONE", 0)
                monitor = directory.monitor_directory(flags, None)
                connect = getattr(monitor, "connect", None)
                if not callable(connect):
                    raise RuntimeError("monitor_connect_unavailable")
                handler_id = connect("changed", _on_downloads_changed)
                downloads_monitor = monitor
                downloads_monitor_handler = (
                    int(handler_id) if isinstance(handler_id, int) else None
                )
                image_status.set_text("Waiting for downloaded image...")
            except Exception:
                _stop_autocatch()
                image_status.set_text("Auto-catch is unavailable. Use Select File.")

        def _on_select_image(_button: object) -> None:
            chooser = Gtk.FileChooserNative.new(
                "Select image",
                self._window,
                Gtk.FileChooserAction.OPEN,
                "Select",
                "Cancel",
            )

            def _on_response(
                dialog: gtk_types.Gtk.FileChooserNative, response_id: int
            ) -> None:
                try:
                    accepted = {
                        Gtk.ResponseType.ACCEPT,
                        Gtk.ResponseType.OK,
                    }
                    if response_id not in accepted:
                        return
                    get_file = getattr(dialog, "get_file", None)
                    if not callable(get_file):
                        image_status.set_text("Failed to resolve selected file.")
                        return
                    file_obj = get_file()
                    get_path = (
                        getattr(file_obj, "get_path", None)
                        if file_obj is not None
                        else None
                    )
                    if not callable(get_path):
                        image_status.set_text("Failed to resolve selected file.")
                        return
                    selected_path = get_path() or ""
                    if not selected_path:
                        image_status.set_text("Failed to resolve selected file.")
                        return
                    ok, error_message = self._validate_image_path(
                        Path(selected_path),
                        min_age_s=0.0,
                    )
                    if not ok:
                        image_status.set_text(error_message)
                        return
                    _stop_autocatch()
                    _set_preview(selected_path, f"Selected: {Path(selected_path).name}")
                finally:
                    destroy = getattr(dialog, "destroy", None)
                    if callable(destroy):
                        destroy()

            chooser.connect("response", _on_response)
            chooser.show()

        def _on_clear_image(_button: object) -> None:
            _stop_autocatch()
            _set_preview(None, "No image selected.")

        find_image_button.connect("clicked", _on_find_image)
        select_image_button.connect("clicked", _on_select_image)
        clear_image_button.connect("clicked", _on_clear_image)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_button = Gtk.Button(label="Apply")
        cancel_button = Gtk.Button(label="Cancel")
        buttons.append(cancel_button)
        buttons.append(apply_button)
        content.append(buttons)

        scroller = Gtk.ScrolledWindow()
        if hasattr(scroller, "set_min_content_width"):
            scroller.set_min_content_width(520)
        if hasattr(scroller, "set_max_content_width"):
            scroller.set_max_content_width(760)
        scroller.set_min_content_height(380)
        if hasattr(scroller, "set_max_content_height"):
            scroller.set_max_content_height(620)
        if hasattr(scroller, "set_propagate_natural_height"):
            scroller.set_propagate_natural_height(True)
        if hasattr(scroller, "set_propagate_natural_width"):
            scroller.set_propagate_natural_width(True)
        scroller.set_child(content)
        if hasattr(popover, "set_child"):
            popover.set_child(scroller)
        if hasattr(popover, "set_size_request"):
            popover.set_size_request(560, -1)

        def _cancel(_button: object) -> None:
            self.hide_anki_upsert()
            on_cancel()

        def _apply(_button: object) -> None:
            def _check_active(check: Any) -> bool:
                getter = getattr(check, "get_active", None)
                if not callable(getter):
                    return False
                try:
                    return bool(getter())
                except Exception:
                    return False

            selected_translations = tuple(
                value for value, check in translation_checks if _check_active(check)
            )
            selected_definitions = tuple(
                value for value, check in definition_checks if _check_active(check)
            )
            selected_examples = tuple(
                value for value, check in example_checks if _check_active(check)
            )
            target_note_ids = tuple(
                note_id for note_id, check in note_checks if _check_active(check)
            )
            decision = AnkiUpsertDecision(
                create_new=_check_active(create_new_check),
                target_note_ids=target_note_ids,
                translation_action=self._action_from_combo(translation_combo),
                definitions_action=self._action_from_combo(definitions_combo),
                examples_action=self._action_from_combo(examples_combo),
                image_action=self._image_action_from_combo(image_combo),
                selected_translations=selected_translations,
                selected_definitions_en=selected_definitions,
                selected_examples_en=selected_examples,
                image_path=selected_image_path,
            )
            self.hide_anki_upsert()
            on_apply(decision)

        cancel_button.connect("clicked", _cancel)
        apply_button.connect("clicked", _apply)
        self._upsert_cleanup = _stop_autocatch
        self._upsert_popover = popover
        if hasattr(popover, "popup"):
            popover.popup()

    def hide_anki_upsert(self) -> None:
        cleanup = self._upsert_cleanup
        self._upsert_cleanup = None
        if cleanup is not None:
            try:
                cleanup()
            except Exception:
                pass
        popover = self._upsert_popover
        self._upsert_popover = None
        if popover is None:
            return
        try:
            popdown = getattr(popover, "popdown", None)
            if callable(popdown):
                popdown()
        except Exception:
            pass
        try:
            unparent = getattr(popover, "unparent", None)
            if callable(unparent):
                unparent()
        except Exception:
            pass

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
        previous_examples_visible = (
            None if previous is None else bool(previous.examples)
        )

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
            translation_visible or definitions_visible or examples_visible
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

        self._autosize_window(state)
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
            en_label.set_max_width_chars(self._max_label_chars)
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
        for definition in state.definitions_items:
            rendered = highlight_to_pango_markup(definition, spec)
            lines.append(f"<i>: {rendered}</i>")
        self._label_definitions.set_markup("\n".join(lines))

    def _clear_children(self, container: gtk_types.Gtk.Box) -> None:
        child = container.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            container.remove(child)
            child = next_child

    def _handle_close_request(self, _window: object) -> bool:
        self.hide_anki_upsert()
        self._on_close_cb()
        return True

    def _handle_key_pressed(
        self, _controller: object, keyval: int, _keycode: int, _state: int
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.hide_anki_upsert()
            self._on_close_cb()
            return True
        return False

    def _handle_add_clicked(self, _button: gtk_types.Gtk.Button) -> None:
        self._on_add()

    def _handle_copy_all_clicked(self, _button: gtk_types.Gtk.Button) -> None:
        self._on_copy_all()

    def _build_action_combo(self) -> Any:
        combo = Gtk.ComboBoxText()
        combo.append("keep_existing", "Keep existing")
        combo.append("replace_with_selected", "Replace with selected")
        combo.append("merge_unique_selected", "Merge selected")
        combo.set_active_id("merge_unique_selected")
        return combo

    def _action_from_combo(self, combo: Any) -> AnkiFieldAction:
        active_id = ""
        getter = getattr(combo, "get_active_id", None)
        if callable(getter):
            active_id = getter() or ""
        if active_id == "keep_existing":
            return AnkiFieldAction.KEEP_EXISTING
        if active_id == "replace_with_selected":
            return AnkiFieldAction.REPLACE_WITH_SELECTED
        return AnkiFieldAction.MERGE_UNIQUE_SELECTED

    def _build_image_action_combo(self) -> Any:
        combo = Gtk.ComboBoxText()
        combo.append("replace_with_selected", "Replace with selected")
        combo.append("keep_existing", "Keep existing")
        combo.set_active_id("replace_with_selected")
        return combo

    def _image_action_from_combo(self, combo: Any) -> AnkiImageAction:
        active_id = ""
        getter = getattr(combo, "get_active_id", None)
        if callable(getter):
            active_id = getter() or ""
        if active_id == "keep_existing":
            return AnkiImageAction.KEEP_EXISTING
        return AnkiImageAction.REPLACE_WITH_SELECTED

    def _downloads_dir(self) -> Path:
        try:
            user_dir_enum = getattr(GLib, "UserDirectory", None)
            if (
                hasattr(GLib, "get_user_special_dir")
                and user_dir_enum is not None
                and hasattr(user_dir_enum, "DIRECTORY_DOWNLOAD")
            ):
                path = GLib.get_user_special_dir(user_dir_enum.DIRECTORY_DOWNLOAD)
                if isinstance(path, str) and path.strip():
                    return Path(path).expanduser()
        except Exception:
            pass
        return Path.home() / "Downloads"

    def _first_download_candidate(
        self,
        directory: Path,
        started_at: float,
    ) -> Path | None:
        if not directory.exists() or not directory.is_dir():
            return None
        candidates: list[tuple[float, Path]] = []
        try:
            for entry in directory.iterdir():
                if not entry.is_file():
                    continue
                suffix = entry.suffix.lower()
                name = entry.name.casefold()
                if suffix not in self._IMAGE_EXTENSIONS:
                    continue
                if name.endswith(self._IMAGE_TEMP_SUFFIXES):
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                if stat.st_mtime < started_at:
                    continue
                candidates.append((stat.st_mtime, entry))
        except OSError:
            return None
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _validate_image_path(self, path: Path, *, min_age_s: float) -> tuple[bool, str]:
        if not path.exists() or not path.is_file():
            return False, "Image file is not accessible."
        suffix = path.suffix.lower()
        if suffix not in self._IMAGE_EXTENSIONS:
            return False, "Unsupported image format."
        if path.name.casefold().endswith(self._IMAGE_TEMP_SUFFIXES):
            return False, "Image is still downloading."
        try:
            stat = path.stat()
        except OSError:
            return False, "Image file is not accessible."
        if stat.st_size <= 0:
            return False, "Image file is empty."
        if stat.st_size > self._IMAGE_MAX_BYTES:
            return False, "Image is too large (max 5 MB)."
        if min_age_s > 0.0 and (time.time() - stat.st_mtime) < min_age_s:
            return False, "too_recent"
        if not self._can_decode_image(path):
            return False, "Invalid image file."
        return True, ""

    def _can_decode_image(self, path: Path) -> bool:
        texture_type = getattr(Gdk, "Texture", None)
        if texture_type is None or not hasattr(texture_type, "new_from_filename"):
            return True
        try:
            texture_type.new_from_filename(str(path))
        except Exception:
            return False
        return True

    def _labeled_row(self, title: str, widget: object) -> gtk_types.Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(label=title)
        label.set_xalign(0.0)
        row.append(label)
        row.append(widget)
        return row

    def _build_value_checks(
        self,
        *,
        title: str,
        values: tuple[str, ...],
        parent: gtk_types.Gtk.Box,
    ) -> list[tuple[str, object]]:
        rows: list[tuple[str, object]] = []
        label = Gtk.Label(label=title)
        label.set_xalign(0.0)
        parent.append(label)
        if not values:
            empty = Gtk.Label(label="(none)")
            empty.set_xalign(0.0)
            parent.append(empty)
            return rows
        for value in values:
            check = Gtk.CheckButton(label=self._shorten(value))
            check.set_active(True)
            parent.append(check)
            rows.append((value, check))
        return rows

    def _shorten(self, value: str, limit: int = 88) -> str:
        text = value.strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}..."

    def _autosize_window(self, state: TranslationViewState) -> None:
        target_width = self._estimate_window_width(state)
        target_height = self._estimate_window_height(state, target_width)
        target = (target_width, target_height)
        if target == self._last_target_size:
            return
        self._window.set_default_size(target_width, target_height)
        self._last_target_size = target

    def _estimate_window_width(self, state: TranslationViewState) -> int:
        max_len = max(
            (
                len(text.strip())
                for text in (
                    state.original,
                    state.translation,
                    *state.definitions_items,
                    *(item.en for item in state.examples),
                )
                if text.strip()
            ),
            default=0,
        )
        extra = max(0, min(220, (max_len - 56) * 2))
        return min(self._MAX_WINDOW_WIDTH, self._DEFAULT_WINDOW_WIDTH + extra)

    def _estimate_window_height(
        self, state: TranslationViewState, target_width: int
    ) -> int:
        measured = self._measured_content_height(target_width)
        if measured is not None:
            return measured
        chars_per_line = max(34, min(84, target_width // 10))
        lines = 0
        lines += self._estimate_lines(state.original, chars_per_line)
        lines += self._estimate_lines(state.translation, chars_per_line)
        lines += sum(
            self._estimate_lines(definition, chars_per_line)
            for definition in state.definitions_items
        )
        lines += sum(
            self._estimate_lines(example.en, chars_per_line)
            for example in state.examples
        )
        lines += len(state.definitions_items) + len(state.examples)
        if state.loading:
            lines += 1
        estimated = 96 + lines * 16
        if state.translation:
            estimated += 8
        if state.definitions_items:
            estimated += 10
        if state.examples:
            estimated += 12
        if not state.translation and not state.definitions_items and not state.examples:
            estimated = self._DEFAULT_WINDOW_HEIGHT
        return max(
            self._MIN_WINDOW_HEIGHT,
            min(self._MAX_WINDOW_HEIGHT, estimated),
        )

    def _measured_content_height(self, target_width: int) -> int | None:
        root = getattr(self, "_root", None)
        if root is None or not hasattr(root, "measure"):
            return None
        try:
            min_height, natural_height, _, _ = root.measure(
                Gtk.Orientation.VERTICAL,
                target_width,
            )
        except Exception:
            return None
        content_height = max(int(min_height), int(natural_height)) + 8
        return max(
            self._MIN_WINDOW_HEIGHT,
            min(self._MAX_WINDOW_HEIGHT, content_height),
        )

    def _estimate_lines(self, text: str, chars_per_line: int) -> int:
        stripped = text.strip()
        if not stripped:
            return 0
        total = 0
        for line in stripped.splitlines():
            clean = line.strip()
            if not clean:
                continue
            total += max(1, (len(clean) + chars_per_line - 1) // chars_per_line)
        return total
