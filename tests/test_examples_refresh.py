from __future__ import annotations

from concurrent.futures import Future
from typing import Any

from desktop_app.application.use_cases.anki_flow import AnkiFlow
from desktop_app.application.use_cases.example_refresh import ExampleRefreshUseCase
from desktop_app.application.use_cases.translation_executor import TranslationExecutor
from desktop_app.application.use_cases.translation_flow import TranslationFlow
from desktop_app.application.view_state import TranslationPresenter
from desktop_app.config import AnkiConfig, AnkiFieldMap, AppConfig, LanguageConfig
from desktop_app.infrastructure.anki import (
    AnkiAddResult,
    AnkiCreateModelResult,
    AnkiIdListResult,
    AnkiListResult,
    AnkiNoteDetailsResult,
    AnkiUpdateResult,
)
from desktop_app.infrastructure.services.history import HistoryStore
from translate_logic.models import Example, FieldValue, TranslationResult


def test_history_store_assigns_entry_id_and_initial_examples_state() -> None:
    store = HistoryStore()
    item = store.add(
        "time",
        "time",
        _result_with_examples("One.", "Two.", "Three.", "Four."),
    )

    assert item.entry_id == 1
    assert item.lookup_text == "time"
    assert item.examples_state.visible_examples == (
        Example("One."),
        Example("Two."),
        Example("Three."),
    )
    assert item.examples_state.collected_examples == item.examples_state.visible_examples


def test_example_refresh_rotates_examples_without_full_translate() -> None:
    translator = _RefreshOnlyTranslator(
        [
            Example("One."),
            Example("Two."),
            Example("Three."),
            Example("Four."),
            Example("Five."),
            Example("Six."),
        ]
    )
    store = HistoryStore()
    flow = TranslationFlow(translator=translator, history=store)
    executor = TranslationExecutor(flow=flow, config=_app_config())
    use_case = ExampleRefreshUseCase(
        translation_executor=executor,
        refresh_pool_limit=6,
    )
    entry = store.add(
        "time",
        "time",
        _result_with_examples("One.", "Two.", "Three."),
    )

    refreshed = use_case.refresh_entry(entry).result()

    assert translator.translate_calls == 0
    assert translator.refresh_calls == [("time", 6)]
    assert refreshed.changed is True
    assert refreshed.item.examples_state.visible_examples == (
        Example("Four."),
        Example("Five."),
        Example("Six."),
    )
    assert refreshed.item.examples_state.collected_examples == (
        Example("One."),
        Example("Two."),
        Example("Three."),
        Example("Four."),
        Example("Five."),
        Example("Six."),
    )


def test_example_refresh_keeps_examples_when_no_new_candidates() -> None:
    translator = _RefreshOnlyTranslator(
        [
            Example("One."),
            Example("Two."),
            Example("Three."),
        ]
    )
    store = HistoryStore()
    flow = TranslationFlow(translator=translator, history=store)
    executor = TranslationExecutor(flow=flow, config=_app_config())
    use_case = ExampleRefreshUseCase(
        translation_executor=executor,
        refresh_pool_limit=6,
    )
    entry = store.add(
        "time",
        "time",
        _result_with_examples("One.", "Two.", "Three."),
    )

    refreshed = use_case.refresh_entry(entry).result()

    assert refreshed.changed is False
    assert refreshed.item.examples_state.visible_examples == (
        Example("One."),
        Example("Two."),
        Example("Three."),
    )
    assert refreshed.item.examples_state.exhausted is True


def test_refresh_state_is_isolated_per_history_entry() -> None:
    translator = _RefreshOnlyTranslator(
        [
            Example("One."),
            Example("Two."),
            Example("Three."),
            Example("Four."),
            Example("Five."),
            Example("Six."),
        ]
    )
    store = HistoryStore()
    flow = TranslationFlow(translator=translator, history=store)
    executor = TranslationExecutor(flow=flow, config=_app_config())
    use_case = ExampleRefreshUseCase(
        translation_executor=executor,
        refresh_pool_limit=6,
    )
    entry_one = store.add(
        "time",
        "time",
        _result_with_examples("One.", "Two.", "Three."),
    )
    entry_two = store.add(
        "time now",
        "time",
        _result_with_examples("One.", "Two.", "Three."),
    )

    use_case.refresh_entry(entry_one).result()
    untouched = store.get(entry_two.entry_id)

    assert untouched is not None
    assert untouched.examples_state.visible_examples == (
        Example("One."),
        Example("Two."),
        Example("Three."),
    )
    assert untouched.examples_state.collected_examples == (
        Example("One."),
        Example("Two."),
        Example("Three."),
    )


def test_prepare_upsert_uses_accumulated_examples_override() -> None:
    flow = AnkiFlow(service=_PreviewOnlyAnkiService())

    preview_result = flow.prepare_upsert(
        _anki_config(),
        "time",
        _result_with_examples("One.", "Two.", "Three."),
        examples_override=("One.", "Two.", "Three.", "Four.", "Five."),
    ).result()

    assert preview_result.error is None
    assert preview_result.preview is not None
    assert preview_result.preview.values.examples_en == (
        "One.",
        "Two.",
        "Three.",
        "Four.",
        "Five.",
    )


def test_translation_presenter_updates_examples_refresh_state() -> None:
    presenter = TranslationPresenter()
    presenter.begin("time")

    final_state = presenter.apply_final(
        _result_with_examples("One.", "Two.", "Three."),
        visible_examples=(Example("One."), Example("Two."), Example("Three.")),
        can_refresh_examples=True,
    )
    refreshing_state = presenter.set_examples_refreshing(
        refreshing_examples=True,
        can_refresh_examples=True,
    )
    updated_state = presenter.update_examples(
        examples=(Example("Four."), Example("Five."), Example("Six.")),
        can_refresh_examples=True,
        refreshing_examples=False,
    )

    assert final_state.can_refresh_examples is True
    assert refreshing_state.refreshing_examples is True
    assert tuple(item.en for item in updated_state.examples) == (
        "Four.",
        "Five.",
        "Six.",
    )


class _RefreshOnlyTranslator:
    def __init__(self, refresh_examples_result: list[Example]) -> None:
        self._refresh_examples_result = tuple(refresh_examples_result)
        self.translate_calls = 0
        self.refresh_calls: list[tuple[str, int]] = []

    def get_cached(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> TranslationResult | None:
        del text, source_lang, target_lang
        return None

    def translate(
        self,
        text: str,
        lookup_text: str,
        source_lang: str,
        target_lang: str,
        on_partial: Any = None,
    ) -> Future[TranslationResult]:
        del text, lookup_text, source_lang, target_lang, on_partial
        self.translate_calls += 1
        raise AssertionError("full translate path must not be used by examples refresh")

    def refresh_examples(
        self,
        lookup_text: str,
        *,
        limit: int,
    ) -> Future[tuple[Example, ...]]:
        self.refresh_calls.append((lookup_text, limit))
        future: Future[tuple[Example, ...]] = Future()
        future.set_result(tuple(self._refresh_examples_result[:limit]))
        return future


class _PreviewOnlyAnkiService:
    def deck_names(self) -> Future[AnkiListResult]:
        raise AssertionError("not used")

    def model_names(self) -> Future[AnkiListResult]:
        raise AssertionError("not used")

    def model_field_names(self, model: str) -> Future[AnkiListResult]:
        del model
        raise AssertionError("not used")

    def find_notes(self, query: str) -> Future[AnkiIdListResult]:
        del query
        future: Future[AnkiIdListResult] = Future()
        future.set_result(AnkiIdListResult(items=[], error=None))
        return future

    def note_details(self, note_ids: list[int]) -> Future[AnkiNoteDetailsResult]:
        del note_ids
        raise AssertionError("not used when there are no matches")

    def add_note(
        self,
        deck: str,
        model: str,
        fields: dict[str, str],
    ) -> Future[AnkiAddResult]:
        del deck, model, fields
        raise AssertionError("not used")

    def update_note_fields(
        self,
        note_id: int,
        fields: dict[str, str],
    ) -> Future[AnkiUpdateResult]:
        del note_id, fields
        raise AssertionError("not used")

    def store_media_path(
        self,
        local_path: str,
        filename: str,
    ) -> Future[AnkiUpdateResult]:
        del local_path, filename
        raise AssertionError("not used")

    def add_field(self, model: str, field_name: str) -> Future[AnkiUpdateResult]:
        del model, field_name
        raise AssertionError("not used")

    def delete_model(self, model: str) -> Future[AnkiUpdateResult]:
        del model
        raise AssertionError("not used")

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]:
        del model_name, fields, front, back, css
        raise AssertionError("not used")


def _result_with_examples(*examples: str) -> TranslationResult:
    return TranslationResult(
        translation_ru=FieldValue.present("время"),
        definitions_en=("definition",),
        examples=tuple(Example(example) for example in examples),
    )


def _app_config() -> AppConfig:
    return AppConfig(
        languages=LanguageConfig(source="en", target="ru"),
        anki=_anki_config(),
    )


def _anki_config() -> AnkiConfig:
    return AnkiConfig(
        deck="deck",
        model="model",
        fields=AnkiFieldMap(
            word="word",
            translation="translation",
            example_en="example_en",
            definitions_en="definitions_en",
            image="image",
        ),
    )
