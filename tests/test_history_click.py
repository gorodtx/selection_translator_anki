from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import Future

import pytest

from desktop_app import gtk_types
from desktop_app.adapters.clipboard_writer import ClipboardWriter
from desktop_app.anki import AnkiAddResult, AnkiCreateModelResult, AnkiListResult
from desktop_app.application.anki_flow import AnkiFlow
from desktop_app.application.history import HistoryItem
from desktop_app.application.translation_executor import TranslationExecutor
from desktop_app.application.translation_flow import TranslationFlow
from desktop_app.application.view_state import TranslationViewState
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig, LanguageConfig
from desktop_app.controllers.anki_controller import AnkiController
from desktop_app.controllers.translation_controller import TranslationController
from translate_logic.models import FieldValue, TranslationResult


class DummyApp(gtk_types.Gtk.Application):
    def __init__(self) -> None:
        pass


class DummyGtkWindow(gtk_types.Gtk.ApplicationWindow):
    def __init__(self) -> None:
        pass


class DummyTranslationWindow:
    def __init__(
        self,
        *,
        app: gtk_types.Gtk.Application,
        on_close: object,
        on_copy_all: object,
        on_add: object,
    ) -> None:
        self.window = DummyGtkWindow()
        self.last_state: TranslationViewState | None = None
        self.presented = False

    def apply_state(self, state: TranslationViewState) -> None:
        self.last_state = state

    def present(self) -> None:
        self.presented = True

    def hide(self) -> None:
        self.presented = False

    def show_banner(self, _notification: object) -> None:
        return


class DummyHistoryWindow:
    def __init__(
        self,
        *,
        app: gtk_types.Gtk.Application,
        on_close: object,
        on_select: object,
    ) -> None:
        self.window = DummyGtkWindow()
        self.presented = False
        self.items: list[HistoryItem] = []

    def present(self) -> None:
        self.presented = True

    def hide(self) -> None:
        self.presented = False

    def refresh(self, items: Iterable[HistoryItem]) -> None:
        self.items = list(items)


class FakeTranslator:
    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Callable[[TranslationResult], None] | None = None,
    ) -> Future[TranslationResult]:
        future: Future[TranslationResult] = Future()
        future.set_result(TranslationResult.empty())
        return future


class FakeHistory:
    def add(self, text: str, result: TranslationResult) -> None:
        return

    def snapshot(self) -> list[HistoryItem]:
        return []


class FakeAnkiPort:
    def deck_names(self) -> Future[AnkiListResult]:
        future: Future[AnkiListResult] = Future()
        future.set_result(AnkiListResult(items=[], error=None))
        return future

    def model_names(self) -> Future[AnkiListResult]:
        future: Future[AnkiListResult] = Future()
        future.set_result(AnkiListResult(items=[], error=None))
        return future

    def add_note(
        self, deck: str, model: str, fields: dict[str, str]
    ) -> Future[AnkiAddResult]:
        future: Future[AnkiAddResult] = Future()
        future.set_result(AnkiAddResult(success=False, error=None, note_id=None))
        return future

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]:
        future: Future[AnkiCreateModelResult] = Future()
        future.set_result(AnkiCreateModelResult(success=False, error=None))
        return future


@pytest.fixture()
def controller(monkeypatch: pytest.MonkeyPatch) -> TranslationController:
    from desktop_app.controllers import history_view as history_view_module
    from desktop_app.controllers import translation_view as translation_view_module

    def build_translation_window(
        *,
        app: gtk_types.Gtk.Application,
        on_close: Callable[[], None],
        on_copy_all: Callable[[], None],
        on_add: Callable[[], None],
    ) -> DummyTranslationWindow:
        return DummyTranslationWindow(
            app=app, on_close=on_close, on_copy_all=on_copy_all, on_add=on_add
        )

    def build_history_window(
        *,
        app: gtk_types.Gtk.Application,
        on_close: Callable[[], None],
        on_select: Callable[[HistoryItem], None],
    ) -> DummyHistoryWindow:
        return DummyHistoryWindow(app=app, on_close=on_close, on_select=on_select)

    monkeypatch.setattr(
        translation_view_module, "_build_window", build_translation_window
    )
    monkeypatch.setattr(history_view_module, "_build_window", build_history_window)

    app = DummyApp()
    config = AppConfig(
        languages=LanguageConfig(source="en", target="ru"),
        anki=AnkiConfig(
            deck="",
            model="",
            fields=AnkiFieldMap(
                word="",
                ipa="",
                translation="",
                example_en="",
                example_ru="",
            ),
        ),
    )
    translation_flow = TranslationFlow(
        translator=FakeTranslator(),
        history=FakeHistory(),
    )
    translation_executor = TranslationExecutor(flow=translation_flow, config=config)
    anki_flow = AnkiFlow(service=FakeAnkiPort())
    anki_controller = AnkiController(anki_flow=anki_flow)
    clipboard_writer = ClipboardWriter()
    return TranslationController(
        app=app,
        translation_executor=translation_executor,
        cancel_active=lambda: None,
        config=config,
        clipboard_writer=clipboard_writer,
        anki_controller=anki_controller,
        on_present_window=lambda _window: None,
        on_open_settings=lambda: None,
    )


def test_history_item_click_opens_translation(
    controller: TranslationController,
) -> None:
    result = TranslationResult(
        translation_ru=FieldValue.present("перевод"),
        ipa_uk=FieldValue.present("ipa"),
        example_en=FieldValue.present("example en"),
        example_ru=FieldValue.present("example ru"),
    )
    item = HistoryItem(text="hello", result=result, expires_at=0.0)

    controller._on_history_item_selected(item)

    assert controller._state.memory.text == "hello"
    assert controller._state.memory.result == result
    assert controller._view.is_visible() is True

    state = controller._view.state
    assert state.original.strip() == "hello"
    assert state.translation == "перевод"
    assert state.loading is False
    assert state.can_add_anki is True
