from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
import importlib

from desktop_app.infrastructure.adapters.clipboard_writer import ClipboardWriter
from desktop_app.application.use_cases.anki_upsert import (
    AnkiUpsertDecision,
    AnkiUpsertPreview,
)
from desktop_app.application.history import HistoryItem
from desktop_app.application.use_cases.translation_executor import TranslationExecutor
from desktop_app.infrastructure.anki.templates import DEFAULT_MODEL_NAME
from desktop_app.config import AppConfig
from desktop_app.presentation.controllers.anki_controller import AnkiController
from .history_view import HistoryViewCoordinator
from .translation_state import TranslationState
from .translation_view import TranslationViewCoordinator
from desktop_app.infrastructure.notifications import Notification
from desktop_app.infrastructure.notifications import messages as notify_messages
from desktop_app import gtk_types
from translate_logic.shared.highlight import build_highlight_spec, highlight_to_markdown
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
        translation_executor: TranslationExecutor,
        cancel_active: Callable[[], None],
        config: AppConfig,
        clipboard_writer: ClipboardWriter,
        anki_controller: AnkiController,
        on_present_window: Callable[[gtk_types.Gtk.ApplicationWindow], None],
        on_open_settings: Callable[[], None],
    ) -> None:
        self._app = app
        self._translation_executor = translation_executor
        self._cancel_active = cancel_active
        self._config = config
        self._clipboard_writer = clipboard_writer
        self._anki_controller = anki_controller
        self._on_present_window = on_present_window
        self._on_open_settings = on_open_settings

        self._translation_future: Future[TranslationResult] | None = None
        self._state = TranslationState()
        self._view = TranslationViewCoordinator(
            app=self._app,
            on_close=self.close_window,
            on_copy_all=self._on_copy_all,
            on_add=self._on_add_clicked,
        )
        self._history = HistoryViewCoordinator(
            app=self._app,
            history_provider=self._translation_executor.history_snapshot,
            on_select=self._on_history_item_selected,
            on_present_window=self._on_present_window,
        )

    def update_config(self, config: AppConfig) -> None:
        self._config = config
        self._translation_executor.update_config(config)

    def show_history_window(self) -> None:
        self._history.show()

    def close_window(self) -> None:
        self.cancel_tasks()
        self._view.hide()

    def cancel_tasks(self) -> None:
        if self._translation_future is not None:
            self._translation_future.cancel()
        self._view.hide_anki_upsert()
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
        should_raise = hotkey or source == "dbus"
        if should_raise and self._view.is_visible():
            window = self._view.window()
            inactive_window = True
            if window is not None:
                is_active = getattr(window, "is_active", None)
                if callable(is_active):
                    try:
                        inactive_window = not bool(is_active())
                    except Exception:
                        inactive_window = True
                else:
                    inactive_window = True
            if inactive_window:
                self._view.hide()
        # Recover Add-to-Anki button after temporary Anki unavailability.
        self.set_anki_available(True)
        normalized = text.strip() if text else ""
        if not normalized:
            return
        if self._state.memory.can_reuse(normalized, loading=self._view.state.loading):
            self._view.reset_original(text)
            if self._state.memory.result is not None:
                self._view.apply_final(self._state.memory.result)
            self._present_window(force=True)
            return
        self.cancel_tasks()
        request_id = self._next_request_id()
        if prepare and not silent:
            self._prepare_request()
        prepared = self._translation_executor.prepare(text)
        if prepared is None:
            return
        if prepared.cached is not None:
            self._state.memory.update(prepared.display_text, prepared.cached)
            self._view.reset_original(prepared.display_text)
            self._view.apply_final(prepared.cached)
            self._present_window()
            return
        self._handle_text(request_id, prepared.display_text, prepared.query_text)

    def set_anki_available(self, available: bool) -> None:
        self._view.set_anki_available(available)

    def _on_history_item_selected(self, item: HistoryItem) -> None:
        if item.result.status is not TranslationStatus.SUCCESS:
            return
        self.cancel_tasks()
        self._next_request_id()
        self._state.memory.update(item.text, item.result)
        self._present_window()
        self._view.begin(item.text)
        self._view.apply_final(item.result)

    def _prepare_request(self) -> None:
        self._state.memory.reset()
        self._view.begin("")

    def _handle_text(self, request_id: int, display_text: str, query_text: str) -> None:
        if not self._state.request.is_active(request_id):
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
        if not self._state.request.is_active(request_id):
            return

        def on_start(display_text: str) -> None:
            if not self._state.request.is_active(request_id):
                return
            self._state.memory.update(display_text, None)
            self._view.begin(display_text)

        def on_partial(result: TranslationResult) -> None:
            GLib.idle_add(self._apply_partial_result, request_id, result)

        def on_complete(result: TranslationResult) -> None:
            GLib.idle_add(self._apply_translation_result, request_id, result)

        def on_error() -> None:
            GLib.idle_add(self._apply_translation_error, request_id)

        self._translation_future = self._translation_executor.run(
            display_text,
            query_text,
            on_start=on_start,
            on_partial=on_partial,
            on_complete=on_complete,
            on_error=on_error,
        )

    def _apply_partial_result(self, request_id: int, result: TranslationResult) -> bool:
        if not self._state.request.is_active(request_id):
            return False
        if result.status is not TranslationStatus.SUCCESS:
            return False
        self._state.memory.update(self._state.memory.text, result)
        self._view.apply_partial(result)
        self._present_window()
        return False

    def _apply_translation_result(
        self, request_id: int, result: TranslationResult
    ) -> bool:
        if not self._state.request.is_active(request_id):
            return False
        self._state.memory.update(self._state.memory.text, result)
        self._translation_executor.register_result(self._state.memory.text, result)
        if result.status is TranslationStatus.SUCCESS:
            if self._history.is_open:
                self._history.refresh()
        self._view.apply_final(result)
        self._present_window()
        return False

    def _apply_translation_error(self, request_id: int) -> bool:
        if not self._state.request.is_active(request_id):
            return False
        self._view.mark_error()
        self._notify(notify_messages.translation_error())
        self._present_window()
        return False

    def _copy_text(self, text: str | None) -> None:
        if not text:
            return
        self._clipboard_writer.copy_text(text)

    def _on_copy_all(self) -> None:
        result = self._state.memory.result
        if result is None:
            return
        lines: list[str] = []
        original = self._state.memory.text.strip()
        highlight_spec = build_highlight_spec(original)
        if original:
            lines.append(f"Original: {original}")
        if result.translation_ru.is_present:
            lines.append(f"Translation: {result.translation_ru.text}")
        if result.definitions_en:
            lines.append("Definitions EN:")
            for index, definition in enumerate(result.definitions_en, start=1):
                highlighted = highlight_to_markdown(definition, highlight_spec)
                lines.append(f"{index}. {highlighted}")
        if result.examples:
            lines.append("Examples:")
            for index, example in enumerate(result.examples, start=1):
                highlighted = highlight_to_markdown(example.en, highlight_spec)
                lines.append(f"{index}. EN: {highlighted}")
        if not lines:
            return
        self._copy_text("\n".join(lines))
        self._notify(notify_messages.copy_success())

    def _on_add_clicked(self) -> None:
        if (
            self._state.memory.result is None
            or self._state.memory.result.status is not TranslationStatus.SUCCESS
        ):
            return
        if not self._anki_controller.is_config_ready(self._config.anki):
            if not self._config.anki.deck:
                self._notify(notify_messages.anki_deck_missing())
            if not self._config.anki.model:
                self._notify(notify_messages.anki_model_required(DEFAULT_MODEL_NAME))
            self._on_open_settings()
            return
        request_id = self._state.request.current_id
        self._anki_controller.prepare_upsert(
            request_id=request_id,
            config=self._config.anki,
            original_text=self._state.memory.text,
            result=self._state.memory.result,
            is_request_active=self._is_request_active,
            on_ready=self._on_anki_upsert_ready,
            set_anki_available=self.set_anki_available,
            notify=self._notify,
        )

    def _on_anki_upsert_ready(self, preview: AnkiUpsertPreview) -> None:
        self._view.show_anki_upsert(
            query_text=self._state.memory.text,
            preview=preview,
            on_apply=lambda decision: self._on_anki_upsert_apply(preview, decision),
            on_cancel=lambda: None,
        )

    def _on_anki_upsert_apply(
        self,
        preview: AnkiUpsertPreview,
        decision: AnkiUpsertDecision,
    ) -> None:
        request_id = self._state.request.current_id
        self._anki_controller.apply_upsert(
            request_id=request_id,
            config=self._config.anki,
            original_text=self._state.memory.text,
            preview=preview,
            decision=decision,
            is_request_active=self._is_request_active,
            on_success=self._on_anki_success,
            on_updated=self._on_anki_updated,
            on_unchanged=self._on_anki_unchanged,
            set_anki_available=self.set_anki_available,
            notify=self._notify,
        )

    def _is_request_active(self, request_id: int) -> bool:
        return self._state.request.is_active(request_id)

    def _next_request_id(self) -> int:
        return self._state.request.next_id()

    def _present_window(self, *, force: bool = False) -> None:
        should_present = force or self._state.request.should_present(
            self._view.is_visible()
        )
        presented = self._view.present(should_present=should_present)
        if not presented:
            return
        self._state.request.mark_presented()
        window = self._view.window()
        if window is not None:
            self._on_present_window(window)

    def _notify(self, notification: Notification) -> None:
        self._view.notify(notification)

    def _on_anki_success(self) -> None:
        self._notify(notify_messages.anki_success())
        self._close_after_success()

    def _on_anki_updated(self) -> None:
        self._notify(notify_messages.anki_updated())
        self._close_after_success()

    def _on_anki_unchanged(self) -> None:
        self._notify(notify_messages.anki_unchanged())

    def _close_after_success(self) -> None:
        self.close_window()
