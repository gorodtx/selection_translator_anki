from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
import importlib

from desktop_app.adapters.clipboard_writer import ClipboardWriter
from desktop_app.application.history import HistoryItem
from desktop_app.application.translation_flow import TranslationFlow
from desktop_app.application.translation_session import TranslationSession
from desktop_app.application.view_state import (
    TranslationPresenter,
    TranslationViewState,
)
from desktop_app.anki.templates import DEFAULT_MODEL_NAME
from desktop_app.config import AppConfig
from desktop_app.controllers.anki_controller import AnkiController
from desktop_app.notifications import Notification
from desktop_app.notifications.models import NotificationDuration
from desktop_app.notifications import messages as notify_messages
from desktop_app.ui import HistoryWindow, TranslationWindow
from desktop_app import gtk_types
from desktop_app import telemetry
from translate_logic.models import TranslationResult, TranslationStatus

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("GLib", "2.0")
GLib = importlib.import_module("gi.repository.GLib")


class TranslationController:
    def __init__(
        self,
        *,
        app: gtk_types.Gtk.Application,
        translation_flow: TranslationFlow,
        cancel_active: Callable[[], None],
        config: AppConfig,
        clipboard_writer: ClipboardWriter,
        anki_controller: AnkiController,
        on_present_window: Callable[[gtk_types.Gtk.ApplicationWindow], None],
        on_open_settings: Callable[[], None],
    ) -> None:
        self._app = app
        self._translation_flow = translation_flow
        self._cancel_active = cancel_active
        self._config = config
        self._clipboard_writer = clipboard_writer
        self._anki_controller = anki_controller
        self._on_present_window = on_present_window
        self._on_open_settings = on_open_settings

        self._translation_view: TranslationWindow | None = None
        self._history_view: HistoryWindow | None = None
        self._history_open = False
        self._history_pending = False
        self._current_request_id = 0
        self._presented_request_id: int | None = None
        self._translation_future: Future[TranslationResult] | None = None
        self._current_text = ""
        self._current_result: TranslationResult | None = None
        self._presenter = TranslationPresenter()
        self._view_state = self._presenter.state

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def ensure_window(self) -> None:
        if self._translation_view is not None:
            return
        self._translation_view = TranslationWindow(
            app=self._app,
            on_close=self.close_window,
            on_copy_all=self._on_copy_all,
            on_add=self._on_add_clicked,
        )
        self._translation_view.apply_state(self._presenter.state)

    def ensure_history_window(self) -> None:
        if self._history_view is not None:
            return
        self._history_view = HistoryWindow(
            app=self._app,
            on_close=self._on_history_closed,
            on_settings=self._on_settings_clicked,
            on_select=self._on_history_item_selected,
        )

    def show_history_window(self) -> None:
        if self._history_pending:
            return
        self._history_pending = True
        GLib.idle_add(self._open_history_window)

    def close_window(self) -> None:
        if self._translation_view is None:
            return
        self.cancel_tasks()
        self._translation_view.hide()

    def cancel_tasks(self) -> None:
        if self._translation_future is not None:
            self._translation_future.cancel()
        self._anki_controller.cancel_pending()
        self._cancel_active()

    def trigger_text(
        self,
        text: str,
        *,
        silent: bool = False,
        prepare: bool = True,
        hotkey: bool = False,
        source: str = "dbus",
    ) -> None:
        telemetry.log_event(
            "translation.trigger",
            hotkey=hotkey,
            silent=silent,
            prepare=prepare,
            source=source,
        )
        request_id = self._next_request_id()
        if prepare and not silent:
            self._prepare_request()
        normalized = text.strip() if text else ""
        if not normalized:
            if hotkey:
                telemetry.log_event("translation.no_text", hotkey=hotkey)
            return
        if (
            self._current_result is not None
            and self._current_result.status is TranslationStatus.SUCCESS
            and self._current_text.strip() == normalized
            and not self._view_state.loading
        ):
            telemetry.log_event("translation.reuse", **telemetry.text_meta(text))
            self._apply_view_state(self._presenter.reset_original(text))
            self._apply_view_state(self._presenter.apply_final(self._current_result))
            self._present_window()
            return
        outcome = self._translation_flow.prepare(
            text, self._config.languages.source, self._config.languages.target
        )
        if outcome.error is not None:
            return
        if outcome.display_text is None or outcome.query_text is None:
            return
        cached = self._translation_flow.cached_result(
            outcome.query_text,
            self._config.languages.source,
            self._config.languages.target,
        )
        if cached is not None:
            telemetry.log_event("translation.cache_fast", **telemetry.text_meta(text))
            self._current_text = outcome.display_text
            self._current_result = cached
            self._apply_view_state(self._presenter.reset_original(outcome.display_text))
            self._apply_view_state(self._presenter.apply_final(cached))
            self._present_window()
            return
        telemetry.log_event("translation.text_ready", **telemetry.text_meta(text))
        self._handle_text(request_id, outcome.display_text, outcome.query_text)

    def set_anki_available(self, available: bool) -> None:
        self._apply_view_state(self._presenter.set_anki_available(available))

    def _open_history_window(self) -> bool:
        self._history_pending = False
        self.ensure_history_window()
        self._refresh_history()
        if self._history_view is not None:
            self._history_open = True
            self._history_view.present()
            self._on_present_window(self._history_view.window)
        return False

    def _on_history_closed(self) -> None:
        self._history_open = False
        if self._history_view is not None:
            self._history_view.hide()

    def _on_settings_clicked(self) -> None:
        self._on_open_settings()

    def _on_history_item_selected(self, item: HistoryItem) -> None:
        if item.result.status is not TranslationStatus.SUCCESS:
            return
        self.cancel_tasks()
        self._next_request_id()
        self._current_text = item.text
        self._current_result = item.result
        self._present_window()
        self._apply_view_state(self._presenter.begin(item.text))
        self._apply_view_state(self._presenter.apply_final(item.result))

    def _refresh_history(self) -> None:
        if self._history_view is None:
            return
        self._history_view.refresh(self._translation_flow.snapshot_history())

    def _prepare_request(self) -> None:
        self._current_text = ""
        self._current_result = None
        self._apply_view_state(self._presenter.begin(""))

    def _handle_text(self, request_id: int, display_text: str, query_text: str) -> None:
        if request_id != self._current_request_id:
            return
        GLib.idle_add(
            self._start_translation_idle,
            request_id,
            display_text,
            query_text,
        )

    def _start_translation_idle(
        self, request_id: int, display_text: str, query_text: str
    ) -> bool:
        self._start_translation(request_id, display_text, query_text)
        return False

    def _start_translation(
        self, request_id: int, display_text: str, query_text: str
    ) -> None:
        if request_id != self._current_request_id:
            return
        telemetry.log_event(
            "translation.start",
            **telemetry.text_meta(display_text),
        )
        session = self._build_translation_session(request_id)
        self._translation_future = session.run(display_text, query_text)

    def _build_translation_session(self, request_id: int) -> TranslationSession:
        def on_start(display_text: str) -> None:
            if request_id != self._current_request_id:
                return
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
            return self._translation_flow.translate(
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
        self._present_window()
        return False

    def _apply_translation_result(
        self, request_id: int, result: TranslationResult
    ) -> bool:
        if request_id != self._current_request_id:
            return False
        self._current_result = result
        self._translation_flow.register_result(self._current_text, result)
        if result.status is TranslationStatus.SUCCESS:
            if self._history_open:
                self._refresh_history()
        self._apply_view_state(self._presenter.apply_final(result))
        self._present_window()
        return False

    def _apply_translation_error(self, request_id: int) -> bool:
        if request_id != self._current_request_id:
            return False
        self._apply_view_state(self._presenter.mark_error())
        self._notify(notify_messages.translation_error())
        self._present_window()
        return False

    def _copy_text(self, text: str | None) -> None:
        if not text:
            return
        self._clipboard_writer.copy_text(text)

    def _apply_view_state(self, state: TranslationViewState) -> None:
        self._view_state = state
        if self._translation_view is not None:
            self._translation_view.apply_state(state)

    def _on_copy_all(self) -> None:
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
        self._notify(notify_messages.copy_success())

    def _on_add_clicked(self) -> None:
        if (
            self._current_result is None
            or self._current_result.status is not TranslationStatus.SUCCESS
        ):
            return
        if not self._anki_controller.is_config_ready(self._config.anki):
            if not self._config.anki.deck:
                self._notify(notify_messages.anki_deck_missing())
            if not self._config.anki.model:
                self._notify(notify_messages.anki_model_required(DEFAULT_MODEL_NAME))
            self._on_open_settings()
            return
        request_id = self._current_request_id
        self._anki_controller.add_note(
            request_id=request_id,
            config=self._config.anki,
            original_text=self._current_text,
            result=self._current_result,
            is_request_active=self._is_request_active,
            on_success=self._on_anki_success,
            set_anki_available=self.set_anki_available,
            notify=self._notify,
        )

    def _is_request_active(self, request_id: int) -> bool:
        return request_id == self._current_request_id

    def _next_request_id(self) -> int:
        self._current_request_id += 1
        self._presented_request_id = None
        return self._current_request_id

    def _present_window(self) -> None:
        if self._translation_view is None:
            self.ensure_window()
        if self._translation_view is None:
            return
        if (
            self._presented_request_id == self._current_request_id
            and self._translation_view.is_visible()
        ):
            return
        self._translation_view.present()
        self._presented_request_id = self._current_request_id
        self._on_present_window(self._translation_view.window)

    def _notify(self, notification: Notification) -> None:
        if self._translation_view is None:
            return
        self._translation_view.show_banner(notification)

    def _on_anki_success(self) -> None:
        self._notify(notify_messages.anki_success())
        GLib.timeout_add(NotificationDuration.SHORT.value, self._close_after_success)

    def _close_after_success(self) -> bool:
        self.close_window()
        return False
