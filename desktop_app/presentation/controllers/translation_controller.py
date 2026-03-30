from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
import importlib

from desktop_app.application.history import HistoryItem
from desktop_app.application.use_cases.example_refresh import (
    ExampleRefreshResult,
    ExampleRefreshUseCase,
)
from desktop_app.infrastructure.adapters.clipboard_writer import ClipboardWriter
from desktop_app.application.use_cases.anki_upsert import (
    AnkiUpsertDecision,
    AnkiUpsertPreview,
)
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
from translate_logic.models import Example, TranslationResult, TranslationStatus

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
        self._examples_refresh_future: Future[ExampleRefreshResult] | None = None
        self._state = TranslationState()
        self._examples_refresh = ExampleRefreshUseCase(
            translation_executor=self._translation_executor
        )
        self._view = TranslationViewCoordinator(
            app=self._app,
            on_close=self.close_window,
            on_copy_all=self._on_copy_all,
            on_add=self._on_add_clicked,
            on_refresh_examples=self._on_refresh_examples_clicked,
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
        self._state.request.invalidate()
        if self._translation_future is not None:
            self._translation_future.cancel()
            self._translation_future = None
        if self._examples_refresh_future is not None:
            self._examples_refresh_future.cancel()
            self._examples_refresh_future = None
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
        raw_text = text.strip() if text else ""
        if not raw_text:
            return
        prepared = self._translation_executor.prepare(raw_text)
        if prepared is None:
            return
        if self._state.memory.can_reuse(
            prepared.display_text,
            loading=self._view.state.loading,
        ):
            self._view.reset_original(prepared.display_text)
            if self._state.memory.result is not None:
                self._apply_current_result_to_view()
            self._present_window(force=True)
            return
        self.cancel_tasks()
        request_id = self._next_request_id()
        if prepared.cached is not None:
            self._remember_success_result(
                display_text=prepared.display_text,
                lookup_text=prepared.lookup_text,
                result=prepared.cached,
            )
            self._view.begin(prepared.display_text)
            self._apply_current_result_to_view()
            self._present_window(force=should_raise or not silent)
            return
        should_prepare_ui = prepare or should_raise or not silent
        if should_prepare_ui:
            self._begin_loading(
                prepared.display_text,
                prepared.lookup_text,
                force_present=should_raise or not silent,
            )
        else:
            self._state.memory.update(
                prepared.display_text,
                None,
                lookup_text=prepared.lookup_text,
            )
        self._handle_text(
            request_id,
            prepared.display_text,
            prepared.network_text,
            prepared.lookup_text,
        )

    def set_anki_available(self, available: bool) -> None:
        self._view.set_anki_available(available)

    def _on_history_item_selected(self, item: HistoryItem) -> None:
        if item.result.status is not TranslationStatus.SUCCESS:
            return
        self.cancel_tasks()
        self._next_request_id()
        self._state.memory.set_entry(item)
        self._present_window()
        self._view.begin(item.text)
        self._apply_current_result_to_view()

    def _prepare_request(self) -> None:
        self._state.memory.reset()
        self._view.begin("")

    def _begin_loading(
        self,
        display_text: str,
        lookup_text: str,
        *,
        force_present: bool,
    ) -> None:
        self._state.memory.update(display_text, None, lookup_text=lookup_text)
        self._view.begin(display_text)
        if force_present:
            self._present_window(force=True)

    def _handle_text(
        self,
        request_id: int,
        display_text: str,
        network_text: str,
        lookup_text: str,
    ) -> None:
        if not self._state.request.is_active(request_id):
            return
        GLib.idle_add(
            self._start_translation_idle,
            request_id,
            display_text,
            network_text,
            lookup_text,
        )

    def _start_translation_idle(
        self,
        request_id: int,
        display_text: str,
        network_text: str,
        lookup_text: str,
    ) -> bool:
        self._start_translation(request_id, display_text, network_text, lookup_text)
        return False

    def _start_translation(
        self,
        request_id: int,
        display_text: str,
        network_text: str,
        lookup_text: str,
    ) -> None:
        if not self._state.request.is_active(request_id):
            return

        def on_start(display_text: str) -> None:
            if not self._state.request.is_active(request_id):
                return
            if (
                self._state.memory.text != display_text
                or not self._view.state.loading
            ):
                self._begin_loading(
                    display_text,
                    self._state.memory.lookup_text,
                    force_present=False,
                )

        def on_partial(result: TranslationResult) -> None:
            GLib.idle_add(self._apply_partial_result, request_id, result)

        def on_complete(result: TranslationResult) -> None:
            GLib.idle_add(self._apply_translation_result, request_id, result)

        def on_error() -> None:
            GLib.idle_add(self._apply_translation_error, request_id)

        self._translation_future = self._translation_executor.run(
            display_text,
            network_text,
            lookup_text,
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
        self._state.memory.update(
            self._state.memory.text,
            result,
            lookup_text=self._state.memory.lookup_text,
        )
        self._view.apply_partial(result)
        self._present_window()
        return False

    def _apply_translation_result(
        self, request_id: int, result: TranslationResult
    ) -> bool:
        if not self._state.request.is_active(request_id):
            return False
        self._translation_future = None
        self._remember_success_result(
            display_text=self._state.memory.text,
            lookup_text=self._state.memory.lookup_text,
            result=result,
        )
        if result.status is TranslationStatus.SUCCESS:
            if self._history.is_open:
                self._history.refresh()
        self._apply_current_result_to_view()
        self._present_window()
        return False

    def _apply_translation_error(self, request_id: int) -> bool:
        if not self._state.request.is_active(request_id):
            return False
        self._translation_future = None
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
        visible_examples = self._current_visible_examples()
        if visible_examples:
            lines.append("Examples:")
            for index, example in enumerate(visible_examples, start=1):
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
            examples_override=self._current_collected_example_texts(),
            is_request_active=self._is_request_active,
            on_ready=self._on_anki_upsert_ready,
            set_anki_available=self.set_anki_available,
            notify=self._notify,
        )

    def _on_refresh_examples_clicked(self) -> None:
        entry = self._current_history_item()
        if entry is None:
            return
        if entry.examples_state.exhausted:
            self._notify(notify_messages.no_more_examples())
            return
        request_id = self._state.request.current_id
        self._view.set_examples_refreshing(
            refreshing_examples=True,
            can_refresh_examples=self._can_refresh_examples(),
        )
        future = self._examples_refresh.refresh_entry(entry)
        future.add_done_callback(
            lambda done: GLib.idle_add(
                self._apply_examples_refresh_result,
                request_id,
                entry.entry_id,
                done,
            )
        )
        self._examples_refresh_future = future

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

    def _apply_examples_refresh_result(
        self,
        request_id: int,
        entry_id: int,
        future: Future[ExampleRefreshResult],
    ) -> bool:
        if not self._state.request.is_active(request_id):
            return False
        if self._state.memory.entry_id != entry_id:
            return False
        self._examples_refresh_future = None
        if future.cancelled():
            self._view.set_examples_refreshing(
                refreshing_examples=False,
                can_refresh_examples=self._can_refresh_examples(),
            )
            return False
        try:
            refresh_result = future.result()
        except Exception as exc:
            self._view.set_examples_refreshing(
                refreshing_examples=False,
                can_refresh_examples=self._can_refresh_examples(),
            )
            self._notify(
                notify_messages.examples_refresh_error(
                    str(exc) or "Failed to refresh examples."
                )
            )
            return False
        self._state.memory.set_entry(refresh_result.item)
        self._view.update_examples(
            examples=refresh_result.item.examples_state.visible_examples,
            can_refresh_examples=self._can_refresh_examples(),
            refreshing_examples=False,
        )
        if self._history.is_open:
            self._history.refresh()
        if not refresh_result.changed:
            self._notify(notify_messages.no_more_examples())
        return False

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

    def _remember_success_result(
        self,
        *,
        display_text: str,
        lookup_text: str,
        result: TranslationResult,
    ) -> None:
        history_item = self._translation_executor.register_result(
            display_text,
            lookup_text,
            result,
        )
        if history_item is not None:
            self._state.memory.set_entry(history_item)
            return
        self._state.memory.update(display_text, result, lookup_text=lookup_text)

    def _apply_current_result_to_view(self) -> None:
        result = self._state.memory.result
        if result is None:
            return
        self._view.apply_final(
            result,
            visible_examples=self._current_visible_examples(),
            can_refresh_examples=self._can_refresh_examples(),
            refreshing_examples=False,
        )

    def _can_refresh_examples(self) -> bool:
        result = self._state.memory.result
        if result is None or result.status is not TranslationStatus.SUCCESS:
            return False
        return bool(self._state.memory.lookup_text.strip())

    def _current_visible_examples(self) -> tuple[Example, ...]:
        if self._state.memory.examples_state is not None:
            return self._state.memory.examples_state.visible_examples
        result = self._state.memory.result
        if result is None:
            return ()
        return tuple(result.examples[:3])

    def _current_collected_example_texts(self) -> tuple[str, ...]:
        if self._state.memory.examples_state is None:
            result = self._state.memory.result
            if result is None:
                return ()
            return tuple(example.en for example in result.examples if example.en.strip())
        return tuple(
            example.en
            for example in self._state.memory.examples_state.collected_examples
            if example.en.strip()
        )

    def _current_history_item(self) -> HistoryItem | None:
        if (
            self._state.memory.entry_id is None
            or self._state.memory.result is None
            or self._state.memory.examples_state is None
        ):
            return None
        return HistoryItem(
            entry_id=self._state.memory.entry_id,
            text=self._state.memory.text,
            lookup_text=self._state.memory.lookup_text,
            result=self._state.memory.result,
            examples_state=self._state.memory.examples_state,
        )
