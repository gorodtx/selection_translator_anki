from __future__ import annotations

import asyncio
from concurrent.futures import Future
from collections.abc import Callable
import importlib
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from desktop_app.anki import AnkiAddResult, AnkiListResult
from desktop_app.application import notify_messages
from desktop_app.application.anki_flow import AnkiOutcome, AnkiResult
from desktop_app.application.notifications import NotificationMessage
from desktop_app.adapters.clipboard import ClipboardAdapter
from desktop_app.adapters.clipboard_writer import ClipboardWriter
from desktop_app.application.clipboard_flow import ClipboardError, ClipboardFlow
from desktop_app.application.query import QueryError
from desktop_app.application.signal_flow import (
    consume_activation_action,
    parse_action_args,
)
from desktop_app.application.translation_session import TranslationSession
from desktop_app.application.view_state import (
    TranslationPresenter,
    TranslationViewState,
)
from desktop_app.adapters.notification_sender import NotificationSender
from desktop_app.config import (
    AppConfig,
    HotkeyBackend,
    HotkeyConfig,
    load_config,
    save_config,
)
from desktop_app.hotkey.manager import HotkeyManager
from desktop_app.services.container import AppServices
from desktop_app.settings import SettingsWindow
from translate_logic.models import TranslationResult, TranslationStatus

APP_ID = "com.translator.desktop"


if TYPE_CHECKING:
    from desktop_app.gtk_types import Gdk, Gio, GLib, Gtk
else:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    Gtk = importlib.import_module("gi.repository.Gtk")
    Gdk = importlib.import_module("gi.repository.Gdk")
    Gio = importlib.import_module("gi.repository.Gio")
    GLib = importlib.import_module("gi.repository.GLib")


def _icon_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    png_path = root / "icons" / "main_icon.png"
    if png_path.exists():
        return png_path
    return root / "icons" / "main_icon.jpg"


def _resolve_app_id() -> str | None:
    if sys.platform.startswith("linux"):
        return APP_ID
    return APP_ID


def _gio_command_line_flag() -> int:
    flags_obj = getattr(Gio, "ApplicationFlags", None)
    if flags_obj is None:
        return 0
    return int(getattr(flags_obj, "HANDLES_COMMAND_LINE", 0))


class TranslatorApp(Gtk.Application):
    def __init__(self) -> None:
        app_id = _resolve_app_id()
        super().__init__(
            application_id=app_id,
            flags=_gio_command_line_flag(),
        )
        logging.getLogger().setLevel(logging.ERROR)
        self._config = load_config()
        self._use_gio_notifications = app_id is not None
        self._notification_sender = NotificationSender(
            app=self if self._use_gio_notifications else None,
            use_gio=self._use_gio_notifications,
            icon_path=_icon_path(),
        )
        self._services = AppServices.create(self._notification_sender.send)
        self._notifier = self._services.notifier
        self._clipboard = ClipboardAdapter()
        self._clipboard_writer = ClipboardWriter()
        self._clipboard_flow = ClipboardFlow(self._clipboard)
        self._pending_action: str | None = None
        self._window: Gtk.ApplicationWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._autostart_window: Gtk.ApplicationWindow | None = None
        self._history_window: Gtk.ApplicationWindow | None = None
        self._history_list: Gtk.ListBox | None = None
        self._history_open = False
        self._history_pending = False
        self._current_request_id = 0
        self._translation_future: Future[TranslationResult] | None = None
        self._anki_future: Future[AnkiAddResult] | None = None
        self._anki_request_id: int | None = None
        self._current_text = ""
        self._current_result: TranslationResult | None = None
        self._last_hotkey_text: str | None = None
        self._presenter = TranslationPresenter()
        self._view_state = self._presenter.state
        self._label_original: Gtk.Label | None = None
        self._label_ipa: Gtk.Label | None = None
        self._label_translation: Gtk.Label | None = None
        self._label_example_en: Gtk.Label | None = None
        self._label_example_ru: Gtk.Label | None = None
        self._spinner: Gtk.Spinner | None = None
        self._add_button: Gtk.Button | None = None
        self._copy_all_button: Gtk.Button | None = None
        self._history_button: Gtk.Button | None = None
        self._settings_button: Gtk.Button | None = None
        self._retry_button: Gtk.Button | None = None
        self._desktop_entry_started = False
        self._hotkey_manager = HotkeyManager(
            app_id=APP_ID,
            notify=self._notification_sender.send,
            callback=self._on_hotkey_triggered,
            hotkey_provider=lambda: self._config.hotkey,
        )
        self._autostart_checked = False
        self._icon_installed: bool | None = None
        self._header_row: Gtk.Box | None = None
        self._row_ipa: Gtk.Box | None = None
        self._row_translation: Gtk.Box | None = None
        self._row_example_en: Gtk.Box | None = None
        self._row_example_ru: Gtk.Box | None = None
        self._sep_after_ipa: Gtk.Separator | None = None
        self._sep_after_translation: Gtk.Separator | None = None
        self._sep_before_actions: Gtk.Separator | None = None
        self._css_applied = False
        self._portal_handle_pending = False
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self.connect("command-line", self._on_command_line)
        self.connect("shutdown", self._on_shutdown)

    def _on_startup(self, _app: Gtk.Application) -> None:
        self.hold()
        self._services.start()
        GLib.set_application_name("Translator")
        GLib.set_prgname("translator")
        self._write_pid_file()
        self._ensure_app_shortcut()
        self._start_tray()
        GLib.idle_add(self._idle_ensure_window)
        self._refresh_anki_lists(update_availability=False)
        self._install_signal_handlers()
        self._ensure_app_shortcut()

    def _idle_ensure_window(self) -> bool:
        self._ensure_window()
        return False

    def _on_activate(self, _app: Gtk.Application) -> None:
        self._ensure_window()
        self._start_tray()
        self._ensure_hotkey_started()
        action = self._consume_activation_action()
        if action != "translate" and self._maybe_prompt_autostart():
            return
        self._check_autostart_once()
        if action == "settings":
            self._open_settings()
            return
        if action == "history":
            self._show_history_window()
            return
        if action == "retry":
            self._refresh_anki_lists(update_availability=True)
            return
        if action == "translate":
            self._trigger_from_clipboard(silent=True, prepare=False, hotkey=True)
            return
        if not self._config.ready_notified:
            self._send_notification(notify_messages.ready_for_hotkey())
            self._config = AppConfig(
                languages=self._config.languages,
                anki=self._config.anki,
                hotkey=self._config.hotkey,
                autostart_prompted=self._config.autostart_prompted,
                autostart_enabled=self._config.autostart_enabled,
                ready_notified=True,
            )
            save_config(self._config)
        return

    def _on_command_line(self, _app: Gtk.Application, command_line: object) -> int:
        text_args: list[str] = []
        get_args = getattr(command_line, "get_arguments", None)
        if callable(get_args):
            args_obj = get_args()
            if isinstance(args_obj, list):
                for arg in args_obj:
                    if isinstance(arg, bytes):
                        text_args.append(arg.decode("utf-8", errors="ignore"))
                    else:
                        text_args.append(str(arg))
        action = parse_action_args(text_args)
        if action is not None:
            self._pending_action = action
        self._on_activate(self)
        return 0

    def _install_signal_handlers(self) -> None:
        self._services.signal_flow.install(
            on_translate=lambda: self._schedule_signal(self._translate_from_signal),
            on_settings=lambda: self._schedule_signal(self._show_settings_from_signal),
            on_history=lambda: self._schedule_signal(self._show_history_from_signal),
            on_retry=lambda: self._schedule_signal(self._retry_from_signal),
        )

    def _consume_activation_action(self) -> str | None:
        if self._pending_action is not None:
            action = self._pending_action
            self._pending_action = None
            return action
        return consume_activation_action()

    def _schedule_signal(self, callback: Callable[[], bool]) -> None:
        GLib.idle_add(callback)

    def _show_settings_from_signal(self) -> bool:
        self._open_settings()
        return False

    def _show_history_from_signal(self) -> bool:
        self._show_history_window()
        return False

    def _translate_from_signal(self) -> bool:
        self._ensure_window()
        self._trigger_from_clipboard(silent=True, hotkey=True)
        return False

    def _retry_from_signal(self) -> bool:
        self._refresh_anki_lists(update_availability=True)
        return False

    def _on_shutdown(self, _app: Gtk.Application) -> None:
        self._hotkey_manager.stop()
        self._cancel_tasks()
        self._services.stop()
        self._stop_tray()
        self._remove_pid_file()
        self.release()

    def _ensure_window(self) -> None:
        if self._window is not None:
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("Translator")
        window.set_default_size(420, -1)
        window.set_resizable(False)
        window.set_hide_on_close(True)
        window.set_decorated(False)
        if hasattr(window, "set_gravity") and hasattr(Gdk, "Gravity"):
            window.set_gravity(Gdk.Gravity.CENTER)
        window.connect("close-request", self._on_close_request)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        window.add_controller(controller)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._label_original = Gtk.Label(label="")
        self._label_original.set_xalign(0.0)
        self._label_original.set_wrap(True)
        self._label_original.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_original.set_max_width_chars(48)
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
        self._label_ipa.set_max_width_chars(48)
        self._label_ipa.add_css_class("ipa")

        self._label_translation = Gtk.Label(label="")
        self._label_translation.set_xalign(0.0)
        self._label_translation.set_wrap(True)
        self._label_translation.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_translation.set_max_width_chars(48)
        self._label_translation.add_css_class("translation")

        self._label_example_en = Gtk.Label(label="")
        self._label_example_en.set_xalign(0.0)
        self._label_example_en.set_wrap(True)
        self._label_example_en.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_example_en.set_max_width_chars(48)
        self._label_example_en.add_css_class("example")

        self._label_example_ru = Gtk.Label(label="")
        self._label_example_ru.set_xalign(0.0)
        self._label_example_ru.set_wrap(True)
        self._label_example_ru.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._label_example_ru.set_max_width_chars(48)
        self._label_example_ru.add_css_class("example")

        self._add_button = Gtk.Button(label="Add to Anki")
        self._add_button.set_sensitive(False)
        self._add_button.connect("clicked", self._on_add_clicked)

        self._settings_button = None

        self._copy_all_button = Gtk.Button(label="Copy All")
        self._copy_all_button.connect("clicked", self._on_copy_all)

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

        self._attach_window_drag(window, root)
        window.set_child(root)
        self._window = window
        self._apply_css()
        self._apply_view_state(self._presenter.state)

    def _ensure_history_window(self) -> None:
        if self._history_window is not None:
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("Translator")
        window.set_default_size(520, 360)
        window.set_resizable(True)
        window.set_hide_on_close(True)
        window.set_decorated(False)
        if hasattr(window, "set_gravity") and hasattr(Gdk, "Gravity"):
            window.set_gravity(Gdk.Gravity.CENTER)
        window.connect("close-request", self._on_history_close)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_history_key_pressed)
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
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(list_box)

        settings_button = Gtk.Button(label="Settings")
        settings_button.connect("clicked", self._on_settings_clicked)

        root.append(title)
        root.append(scroller)
        root.append(settings_button)

        self._attach_window_drag(window, root)
        window.set_child(root)
        self._history_window = window
        self._history_list = list_box
        self._apply_css()

    def _on_history_close(self, window: Gtk.ApplicationWindow) -> bool:
        self._history_open = False
        window.hide()
        return True

    def _on_history_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: int,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            if self._history_window is not None:
                self._history_open = False
                self._history_window.hide()
            return True
        return False

    def _show_history_window(self, *_args: object) -> None:
        if self._history_pending:
            return
        self._history_pending = True
        GLib.idle_add(self._open_history_window)

    def _open_history_window(self) -> bool:
        self._history_pending = False
        self._ensure_history_window()
        self._refresh_history()
        if self._history_window is not None:
            self._history_open = True
            self._history_window.present()
            self._schedule_portal_handle_update(self._history_window)
        return False

    def _on_history_clicked(self, _button: Gtk.Button) -> None:
        self._show_history_window()

    def _refresh_history(self) -> None:
        if self._history_list is None:
            return
        child = self._history_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._history_list.remove(child)
            child = next_child
        for item in self._services.translation_flow.snapshot_history():
            if item.result.status is not TranslationStatus.SUCCESS:
                continue
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
            self._history_list.append(row)

    def _attach_window_drag(
        self, window: Gtk.ApplicationWindow, widget: Gtk.Widget
    ) -> None:
        gesture = Gtk.GestureDrag()
        gesture.set_button(1)
        gesture.connect(
            "drag-begin", lambda g, x, y: self._on_drag_begin(window, g, x, y)
        )
        widget.add_controller(gesture)

    def _on_drag_begin(
        self,
        window: Gtk.ApplicationWindow,
        gesture: Gtk.GestureDrag,
        x: float,
        y: float,
    ) -> None:
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

    def _apply_css(self) -> None:
        if self._css_applied:
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
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._css_applied = True

    def _field_row(self, label: Gtk.Label) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label.set_hexpand(True)
        row.append(label)
        return row

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: int,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._close_window()
            return True
        return False

    def _on_close_request(self, window: Gtk.ApplicationWindow) -> bool:
        self._cancel_tasks()
        window.hide()
        return True

    def _close_window(self) -> None:
        if self._window is None:
            return
        self._cancel_tasks()
        self._window.hide()

    def _cancel_tasks(self) -> None:
        if self._translation_future is not None:
            self._translation_future.cancel()
        if self._anki_future is not None:
            self._anki_future.cancel()
        self._services.cancel_active()

    def _trigger_from_clipboard(
        self,
        *,
        silent: bool = False,
        prepare: bool = True,
        hotkey: bool = False,
    ) -> None:
        request_id = self._next_request_id()
        if prepare and not silent:
            self._prepare_request()
        self._clipboard_flow.request_text(
            hotkey=hotkey,
            on_text=lambda text: self._on_clipboard_text_ready(
                request_id, text, silent, hotkey
            ),
            on_error=lambda error: self._on_clipboard_error(
                request_id, error, silent, hotkey
            ),
        )

    def _prepare_request(self) -> None:
        self._present_window()
        self._current_text = ""
        self._current_result = None
        self._apply_view_state(self._presenter.begin(""))

    def _on_clipboard_text_ready(
        self, request_id: int, text: str, silent: bool, hotkey: bool
    ) -> None:
        if request_id != self._current_request_id:
            return
        normalized = text.strip() if text else ""
        if not normalized:
            if hotkey:
                return
            if not silent:
                self._send_notification(notify_messages.no_text())
            return
        if hotkey:
            if normalized == self._last_hotkey_text:
                return
            self._last_hotkey_text = normalized
        self._handle_text(request_id, text, silent)

    def _on_clipboard_error(
        self, request_id: int, error: ClipboardError, silent: bool, hotkey: bool
    ) -> None:
        if request_id != self._current_request_id:
            return
        if hotkey:
            return
        if silent:
            return
        if error is ClipboardError.NO_DISPLAY:
            self._send_notification(notify_messages.no_display())
            return
        if error is ClipboardError.NO_CLIPBOARD:
            self._send_notification(notify_messages.no_clipboard())
            return
        if error is ClipboardError.NO_TEXT:
            self._send_notification(notify_messages.no_text())

    def _handle_text(self, request_id: int, text: str, silent: bool) -> None:
        if request_id != self._current_request_id:
            return
        outcome = self._services.translation_flow.prepare(
            text, self._config.languages.source, self._config.languages.target
        )
        if outcome.error is not None:
            if not silent:
                self._notify_query_error(outcome.error)
            return
        if outcome.display_text is None or outcome.query_text is None:
            return
        GLib.idle_add(
            self._start_translation_idle,
            request_id,
            outcome.display_text,
            outcome.query_text,
        )

    def _start_translation_idle(
        self, request_id: int, display_text: str, query_text: str
    ) -> bool:
        self._start_translation(request_id, display_text, query_text)
        return False

    def _notify_query_error(self, error: QueryError) -> None:
        if error is QueryError.NO_TEXT:
            self._send_notification(notify_messages.no_text())
            return
        if error is QueryError.NO_ENGLISH:
            self._send_notification(notify_messages.no_english())
            return
        if error is QueryError.UNSUPPORTED_LANGUAGE:
            self._send_notification(notify_messages.unsupported_language())

    def _start_translation(
        self, request_id: int, display_text: str, query_text: str
    ) -> None:
        if request_id != self._current_request_id:
            return
        session = self._build_translation_session(request_id)
        self._translation_future = session.run(display_text, query_text)

    def _build_translation_session(self, request_id: int) -> TranslationSession:
        def on_start(display_text: str) -> None:
            if request_id != self._current_request_id:
                return
            self._present_window()
            self._current_text = display_text
            self._current_result = None
            self._apply_view_state(self._presenter.begin(display_text))
            if self._translation_future is not None:
                self._translation_future.cancel()

        def on_partial(result: TranslationResult) -> None:
            GLib.idle_add(self._apply_partial_result, request_id, result)

        def on_complete(result: TranslationResult) -> None:
            GLib.idle_add(self._apply_translation_result, request_id, result)

        def on_error() -> None:
            GLib.idle_add(self._apply_translation_error, request_id)

        def start_translation(
            query_text: str, on_partial_callback: Callable[[TranslationResult], None]
        ) -> Future[TranslationResult]:
            return self._services.translation_flow.translate(
                query_text,
                self._config.languages.source,
                self._config.languages.target,
                on_partial=on_partial_callback,
            )

        return TranslationSession(
            start_translation=start_translation,
            on_start=on_start,
            on_partial=on_partial,
            on_complete=on_complete,
            on_error=on_error,
        )

    def _apply_partial_result(self, request_id: int, result: TranslationResult) -> bool:
        if request_id != self._current_request_id:
            return False
        if result.status is not TranslationStatus.SUCCESS:
            return False
        self._current_result = result
        self._apply_view_state(self._presenter.apply_partial(result))
        return False

    def _apply_translation_result(
        self, request_id: int, result: TranslationResult
    ) -> bool:
        if request_id != self._current_request_id:
            return False
        self._current_result = result
        self._services.translation_flow.register_result(self._current_text, result)
        if result.status is TranslationStatus.SUCCESS:
            if self._history_open:
                self._refresh_history()
        self._apply_view_state(self._presenter.apply_final(result))
        if result.status is not TranslationStatus.SUCCESS:
            self._send_notification(notify_messages.translation_failed())
        return False

    def _apply_translation_error(self, request_id: int) -> bool:
        if request_id != self._current_request_id:
            return False
        self._apply_view_state(self._presenter.mark_error())
        self._send_notification(notify_messages.translation_failed())
        return False

    def _copy_text(self, text: str | None) -> None:
        if not text:
            return
        self._clipboard_writer.copy_text(text)

    def _apply_view_state(self, state: TranslationViewState) -> None:
        self._view_state = state
        if self._label_original is not None:
            self._label_original.set_text(state.original)
        if self._label_ipa is not None:
            self._label_ipa.set_text(state.ipa)
        if self._label_translation is not None:
            self._label_translation.set_text(state.translation)
        if self._label_example_en is not None:
            self._label_example_en.set_text(state.example_en)
        if self._label_example_ru is not None:
            self._label_example_ru.set_text(state.example_ru)
        if self._spinner is not None:
            if state.loading:
                self._spinner.set_visible(True)
                self._spinner.start()
            else:
                self._spinner.stop()
                self._spinner.set_visible(False)
        header_visible = bool(state.original.strip()) or state.loading
        if self._header_row is not None:
            self._header_row.set_visible(header_visible)

        ipa_visible = bool(state.ipa.strip())
        translation_visible = bool(state.translation.strip())
        example_en_visible = bool(state.example_en.strip())
        example_ru_visible = bool(state.example_ru.strip())

        if self._row_ipa is not None:
            self._row_ipa.set_visible(ipa_visible)
        if self._row_translation is not None:
            self._row_translation.set_visible(translation_visible)
        if self._row_example_en is not None:
            self._row_example_en.set_visible(example_en_visible)
        if self._row_example_ru is not None:
            self._row_example_ru.set_visible(example_ru_visible)

        if self._sep_after_ipa is not None:
            self._sep_after_ipa.set_visible(ipa_visible and translation_visible)
        if self._sep_after_translation is not None:
            self._sep_after_translation.set_visible(
                translation_visible and (example_en_visible or example_ru_visible)
            )
        if self._sep_before_actions is not None:
            self._sep_before_actions.set_visible(
                ipa_visible
                or translation_visible
                or example_en_visible
                or example_ru_visible
            )
        if self._add_button is not None:
            self._add_button.set_sensitive(state.can_add_anki)

    def _on_copy_all(self, _button: Gtk.Button) -> None:
        result = self._current_result
        if result is None:
            return
        lines: list[str] = []
        original = self._current_text.strip()
        if original:
            lines.append(f"Original: {original}")
        if result.ipa_uk.is_present:
            lines.append(f"IPA: {result.ipa_uk.text}")
        if result.translation_ru.is_present:
            lines.append(f"Translation: {result.translation_ru.text}")
        if result.example_en.is_present:
            lines.append(f"Example EN: {result.example_en.text}")
        if result.example_ru.is_present:
            lines.append(f"Example RU: {result.example_ru.text}")
        if not lines:
            return
        self._copy_text("\n".join(lines))

    def _on_add_clicked(self, _button: Gtk.Button) -> None:
        if (
            self._current_result is None
            or self._current_result.status is not TranslationStatus.SUCCESS
        ):
            self._send_notification(notify_messages.translation_failed())
            return
        if not self._services.anki_flow.is_config_ready(self._config.anki):
            self._send_notification(notify_messages.anki_config_required())
            self._open_settings()
            return
        if self._anki_future is not None:
            self._anki_future.cancel()
        request_id = self._current_request_id
        self._anki_request_id = request_id

        def on_done(result: AnkiResult) -> None:
            GLib.idle_add(self._apply_anki_result, request_id, result)

        future = self._services.anki_flow.add_note(
            self._config.anki,
            self._current_text,
            self._current_result,
            on_done=on_done,
            on_unavailable=self._mark_anki_unavailable,
        )
        self._anki_future = future

    def _apply_anki_result(self, request_id: int, result: AnkiResult) -> bool:
        if (
            request_id != self._current_request_id
            or request_id != self._anki_request_id
        ):
            return False
        if result.outcome is AnkiOutcome.SUCCESS:
            self._close_window()
            return False
        if result.outcome is AnkiOutcome.DUPLICATE:
            self._send_notification(notify_messages.anki_duplicate())
            return False
        if result.outcome is AnkiOutcome.UNAVAILABLE:
            self._send_notification(notify_messages.anki_unavailable())
            self._apply_view_state(self._presenter.set_anki_available(False))
            return False
        self._send_notification(
            notify_messages.anki_error(result.message or "Failed to add card.")
        )
        return False

    def _mark_anki_unavailable(self) -> None:
        self._apply_view_state(self._presenter.set_anki_available(False))

    def _on_settings_clicked(self, _button: Gtk.Button) -> None:
        self._open_settings()

    def _open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                app=self,
                config=self._config,
                runtime=self._services.runtime,
                notifier=self._notifier,
                anki_flow=self._services.anki_flow,
                on_save=self._on_settings_saved,
                on_hotkey_apply=self._on_hotkey_applied,
            )
        else:
            self._settings_window.update_config(self._config)
        self._settings_window.present()
        self._schedule_portal_handle_update(self._settings_window.window)

    def _on_settings_saved(self, config: AppConfig) -> None:
        previous = self._config
        self._config = config
        save_config(config)
        if previous.hotkey != config.hotkey:
            self._hotkey_manager.restart()

    def _on_hotkey_applied(self, hotkey: HotkeyConfig) -> None:
        previous = self._config.hotkey
        if previous == hotkey:
            return
        self._config = AppConfig(
            languages=self._config.languages,
            anki=self._config.anki,
            hotkey=hotkey,
            autostart_prompted=self._config.autostart_prompted,
            autostart_enabled=self._config.autostart_enabled,
            ready_notified=self._config.ready_notified,
        )
        save_config(self._config)
        self._hotkey_manager.restart()
        if hotkey.backend == HotkeyBackend.SYSTEM:
            self._send_notification(notify_messages.hotkey_system_hint())
        else:
            self._send_notification(notify_messages.hotkey_registered())

    def _on_retry_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_anki_lists(update_availability=True)

    def _refresh_anki_lists(self, update_availability: bool) -> None:
        future = self._services.anki_flow.refresh_decks()
        future.add_done_callback(
            lambda done_future: GLib.idle_add(
                self._apply_anki_lists, done_future, update_availability
            )
        )

    def _apply_anki_lists(
        self, future: Future[AnkiListResult], update_availability: bool
    ) -> bool:
        if future.cancelled():
            return False
        try:
            deck_result = future.result()
        except Exception:
            return False
        if update_availability:
            self._apply_view_state(
                self._presenter.set_anki_available(deck_result.error is None)
            )
        return False

    def _send_notification(self, message: NotificationMessage) -> None:
        self._notifier.send(message)

    def _on_hotkey_triggered(self) -> None:
        self._check_autostart_once()
        self._trigger_from_clipboard(silent=True, prepare=False, hotkey=True)

    def _maybe_prompt_autostart(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        if self._services.desktop_entry_flow.autostart_entry_path().exists():
            return False
        self._show_autostart_prompt()
        return True

    def _write_pid_file(self) -> None:
        path = self._services.process_flow.pid_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            return

    def _remove_pid_file(self) -> None:
        path = self._services.process_flow.pid_path()
        try:
            if path.exists():
                path.unlink()
        except OSError:
            return

    def _show_autostart_prompt(self) -> None:
        if self._autostart_window is not None:
            self._autostart_window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("Translator")
        window.set_default_size(420, 180)
        window.set_resizable(False)
        window.set_hide_on_close(True)
        window.set_decorated(False)
        if hasattr(window, "set_gravity") and hasattr(Gdk, "Gravity"):
            window.set_gravity(Gdk.Gravity.CENTER)
        window.connect("close-request", self._on_autostart_close)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_autostart_key_pressed)
        window.add_controller(controller)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        container.set_margin_top(12)
        container.set_margin_bottom(12)
        container.set_margin_start(12)
        container.set_margin_end(12)

        label = Gtk.Label(
            label=(
                "Allow Translator to run in the background and start with the system?"
            )
        )
        label.set_wrap(True)
        label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        label.set_xalign(0.0)
        label.set_max_width_chars(48)
        container.append(label)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        allow_button = Gtk.Button(label="Allow")
        deny_button = Gtk.Button(label="Not now")
        allow_button.connect("clicked", self._on_autostart_allow)
        deny_button.connect("clicked", self._on_autostart_deny)
        buttons.append(allow_button)
        buttons.append(deny_button)
        container.append(buttons)

        self._attach_window_drag(window, container)
        window.set_child(container)
        self._autostart_window = window
        window.present()
        self._schedule_portal_handle_update(window)

    def _on_autostart_close(self, window: Gtk.ApplicationWindow) -> bool:
        window.hide()
        return True

    def _on_autostart_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: int,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            if self._autostart_window is not None:
                self._autostart_window.hide()
            return True
        return False

    def _on_autostart_allow(self, _button: Gtk.Button) -> None:
        self._enable_autostart()
        self._update_autostart_config(True)
        if self._autostart_window is not None:
            self._autostart_window.hide()

    def _on_autostart_deny(self, _button: Gtk.Button) -> None:
        self._update_autostart_config(False)
        if self._autostart_window is not None:
            self._autostart_window.hide()

    def _update_autostart_config(self, enabled: bool) -> None:
        self._config = self._services.autostart_flow.update_config(
            self._config, enabled
        )
        save_config(self._config)

    def _enable_autostart(self) -> None:
        self._services.desktop_entry_flow.ensure_autostart(self._icon_path())

    def _ensure_app_shortcut(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        if self._desktop_entry_started:
            return
        try:
            loop = self._services.runtime.loop
        except RuntimeError:
            return
        self._desktop_entry_started = True

        def work() -> None:
            self._services.desktop_entry_flow.ensure_shortcut(self._icon_path())
            self._services.desktop_entry_flow.cleanup_entries()
            self._services.desktop_entry_flow.cleanup_cache()

        asyncio.run_coroutine_threadsafe(asyncio.to_thread(work), loop)

    def _check_autostart_once(self) -> None:
        if self._autostart_checked or not sys.platform.startswith("linux"):
            return
        self._autostart_checked = True
        autostart_exists = (
            self._services.desktop_entry_flow.autostart_entry_path().exists()
        )
        if self._config.autostart_enabled and not autostart_exists:
            self._update_autostart_config(False)
            self._send_notification(notify_messages.autostart_missing())

    def _icon_path(self) -> Path:
        return _icon_path()

    def _start_tray(self) -> None:
        self._services.tray_flow.start(self._icon_path())

    def _stop_tray(self) -> None:
        self._services.tray_flow.stop()

    def _ensure_hotkey_started(self) -> None:
        self._hotkey_manager.ensure_started()

    def _next_request_id(self) -> int:
        self._current_request_id += 1
        return self._current_request_id

    def _present_window(self) -> None:
        if self._window is None:
            return
        self._window.present()
        self._schedule_portal_handle_update(self._window)

    def _schedule_portal_handle_update(self, window: Gtk.ApplicationWindow) -> None:
        if self._hotkey_manager.runtime_backend() is not HotkeyBackend.PORTAL:
            return
        GLib.idle_add(self._maybe_update_portal_handle_from, window)

    def _maybe_update_portal_handle_from(
        self, window: Gtk.ApplicationWindow | None
    ) -> bool:
        if window is None:
            return False
        if self._hotkey_manager.runtime_backend() is not HotkeyBackend.PORTAL:
            return False
        self._request_portal_handle(window)
        return False

    def _request_portal_handle(self, window: Gtk.ApplicationWindow) -> None:
        if self._portal_handle_pending:
            return
        surface = window.get_surface()
        if surface is None or not hasattr(surface, "export_handle"):
            return
        self._portal_handle_pending = True

        def on_export(_surface: object, handle: str, _data: object) -> None:
            self._portal_handle_pending = False
            if handle:
                self._hotkey_manager.update_portal_handle(handle)

        try:
            exported = surface.export_handle(on_export, None)
        except Exception:
            self._portal_handle_pending = False
            return
        if not exported:
            self._portal_handle_pending = False
