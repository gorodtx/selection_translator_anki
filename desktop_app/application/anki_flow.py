from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
import html
import re

from desktop_app.anki import (
    AnkiAddResult,
    AnkiCreateModelResult,
    AnkiIdListResult,
    AnkiListResult,
    AnkiNoteDetailsResult,
    AnkiUpdateResult,
)
from desktop_app.application.anki_upsert import (
    AnkiFieldAction,
    AnkiUpsertDecision,
    AnkiUpsertMatch,
    AnkiUpsertPreview,
    AnkiUpsertValues,
)
from desktop_app.application.ports import AnkiPort
from desktop_app.config import AnkiConfig
from translate_logic.highlight import (
    HighlightSpec,
    build_highlight_spec,
    highlight_to_html_mark,
)
from translate_logic.models import TranslationResult

_WHITESPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_NUMBER_RE = re.compile(r"^\s*\d+\.\s*")


class AnkiOutcome(Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AnkiResult:
    outcome: AnkiOutcome
    message: str | None = None


@dataclass(frozen=True, slots=True)
class AnkiUpsertPreviewResult:
    preview: AnkiUpsertPreview | None
    error: AnkiResult | None


@dataclass(slots=True)
class AnkiFlow:
    service: AnkiPort

    def refresh_decks(self) -> Future[AnkiListResult]:
        return self.service.deck_names()

    def model_names(self) -> Future[AnkiListResult]:
        return self.service.model_names()

    def is_config_ready(self, config: AnkiConfig) -> bool:
        fields = config.fields
        return all(
            [
                config.deck,
                config.model,
                fields.word,
                fields.translation,
                fields.example_en,
                fields.definitions_en,
            ]
        )

    def build_fields(
        self, config: AnkiConfig, original_text: str, result: TranslationResult
    ) -> dict[str, str]:
        values = _values_from_result(result)
        return self._build_fields_from_values(config, original_text, values)

    def add_note(
        self,
        config: AnkiConfig,
        original_text: str,
        result: TranslationResult,
        on_done: Callable[[AnkiResult], None],
        *,
        on_unavailable: Callable[[], None] | None = None,
    ) -> Future[AnkiAddResult]:
        fields = self.build_fields(config, original_text, result)
        future = self.service.add_note(config.deck, config.model, fields)
        future.add_done_callback(
            lambda done: self._handle_add_result(done, on_done, on_unavailable)
        )
        return future

    def prepare_upsert(
        self,
        config: AnkiConfig,
        original_text: str,
        result: TranslationResult,
    ) -> Future[AnkiUpsertPreviewResult]:
        completion: Future[AnkiUpsertPreviewResult] = Future()
        values = _values_from_result(result)
        query = _build_deck_model_query(config.deck, config.model)
        find_future = self.service.find_notes(query)

        def _finish(payload: AnkiUpsertPreviewResult) -> None:
            if completion.cancelled() or completion.done():
                return
            completion.set_result(payload)

        def _on_find(done: Future[AnkiIdListResult]) -> None:
            if completion.cancelled() or completion.done():
                return
            if done.cancelled():
                completion.cancel()
                return
            try:
                find_result = done.result()
            except Exception as exc:
                _finish(
                    AnkiUpsertPreviewResult(
                        preview=None,
                        error=_result_for_error(str(exc) or "Failed to query Anki."),
                    )
                )
                return
            if find_result.error is not None:
                _finish(
                    AnkiUpsertPreviewResult(
                        preview=None,
                        error=_result_for_error(find_result.error),
                    )
                )
                return
            note_ids = find_result.items
            if not note_ids:
                _finish(
                    AnkiUpsertPreviewResult(
                        preview=AnkiUpsertPreview(values=values, matches=()),
                        error=None,
                    )
                )
                return
            details_future = self.service.note_details(note_ids)

            def _on_details(done_details: Future[AnkiNoteDetailsResult]) -> None:
                if completion.cancelled() or completion.done():
                    return
                if done_details.cancelled():
                    completion.cancel()
                    return
                try:
                    details_result = done_details.result()
                except Exception as exc:
                    _finish(
                        AnkiUpsertPreviewResult(
                            preview=None,
                            error=_result_for_error(
                                str(exc) or "Failed to load note details."
                            ),
                        )
                    )
                    return
                if details_result.error is not None:
                    _finish(
                        AnkiUpsertPreviewResult(
                            preview=None,
                            error=_result_for_error(details_result.error),
                        )
                    )
                    return
                normalized_word = _normalize_token(original_text)
                field_map = config.fields
                matches: list[AnkiUpsertMatch] = []
                for details in details_result.items:
                    stored_word = details.fields.get(field_map.word, "")
                    if _normalize_token(_strip_html(stored_word)) != normalized_word:
                        continue
                    matches.append(
                        AnkiUpsertMatch(
                            note_id=details.note_id,
                            word=stored_word,
                            translation=details.fields.get(field_map.translation, ""),
                            definitions_en=details.fields.get(
                                field_map.definitions_en, ""
                            ),
                            examples_en=details.fields.get(field_map.example_en, ""),
                        )
                    )
                _finish(
                    AnkiUpsertPreviewResult(
                        preview=AnkiUpsertPreview(
                            values=values,
                            matches=tuple(matches),
                        ),
                        error=None,
                    )
                )

            details_future.add_done_callback(_on_details)

        find_future.add_done_callback(_on_find)
        return completion

    def apply_upsert(
        self,
        config: AnkiConfig,
        original_text: str,
        preview: AnkiUpsertPreview,
        decision: AnkiUpsertDecision,
    ) -> Future[AnkiResult]:
        completion: Future[AnkiResult] = Future()
        selected_values = _selected_values(decision)

        if decision.create_new or not decision.target_note_ids:
            create_values = _fallback_values(preview.values, selected_values)
            fields = self._build_fields_from_values(config, original_text, create_values)
            add_future = self.service.add_note(config.deck, config.model, fields)

            def _on_add(done: Future[AnkiAddResult]) -> None:
                if completion.cancelled() or completion.done():
                    return
                if done.cancelled():
                    completion.cancel()
                    return
                try:
                    add_result = done.result()
                except Exception as exc:
                    completion.set_result(
                        _result_for_error(str(exc) or "Failed to add card.")
                    )
                    return
                if add_result.success:
                    completion.set_result(AnkiResult(outcome=AnkiOutcome.SUCCESS))
                    return
                message = add_result.error or "Failed to add card."
                completion.set_result(_result_for_error(message))

            add_future.add_done_callback(_on_add)
            return completion

        match_map = {match.note_id: match for match in preview.matches}
        target_note_ids = tuple(dict.fromkeys(decision.target_note_ids))
        updates: list[tuple[int, dict[str, str]]] = []
        for note_id in target_note_ids:
            match = match_map.get(note_id)
            if match is None:
                continue
            update_fields = self._build_update_fields(
                config=config,
                original_text=original_text,
                match=match,
                decision=decision,
                selected=selected_values,
            )
            if update_fields:
                updates.append((note_id, update_fields))

        if not updates:
            completion.set_result(AnkiResult(outcome=AnkiOutcome.UNCHANGED))
            return completion

        pending = len(updates)
        failures: list[str] = []

        def _done() -> None:
            if completion.cancelled() or completion.done():
                return
            if failures:
                completion.set_result(_result_for_error(failures[0]))
                return
            completion.set_result(AnkiResult(outcome=AnkiOutcome.UPDATED))

        def _on_update(done: Future[AnkiUpdateResult]) -> None:
            nonlocal pending
            if completion.cancelled() or completion.done():
                return
            if not done.cancelled():
                try:
                    update_result = done.result()
                    if not update_result.success:
                        failures.append(update_result.error or "Failed to update card.")
                except Exception as exc:
                    failures.append(str(exc) or "Failed to update card.")
            pending -= 1
            if pending <= 0:
                _done()

        for note_id, fields in updates:
            update_future = self.service.update_note_fields(note_id, fields)
            update_future.add_done_callback(_on_update)
        return completion

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]:
        return self.service.create_model(model_name, fields, front, back, css)

    def _build_fields_from_values(
        self,
        config: AnkiConfig,
        original_text: str,
        values: AnkiUpsertValues,
    ) -> dict[str, str]:
        fields = config.fields
        highlight_spec = build_highlight_spec(original_text)
        payload = {
            fields.word: original_text,
            fields.translation: _format_translation_html(values.translations),
            fields.example_en: _format_ranked_html(values.examples_en, highlight_spec),
            fields.definitions_en: _format_ranked_html(
                values.definitions_en, highlight_spec
            ),
        }
        return payload

    def _build_update_fields(
        self,
        *,
        config: AnkiConfig,
        original_text: str,
        match: AnkiUpsertMatch,
        decision: AnkiUpsertDecision,
        selected: AnkiUpsertValues,
    ) -> dict[str, str]:
        fields = config.fields
        highlight_spec = build_highlight_spec(original_text)
        existing_translations = _parse_translation_values(match.translation)
        existing_definitions = _parse_ranked_values(match.definitions_en)
        existing_examples = _parse_ranked_values(match.examples_en)

        next_translations = _apply_action(
            existing=existing_translations,
            selected=list(selected.translations),
            action=decision.translation_action,
        )
        next_definitions = _apply_action(
            existing=existing_definitions,
            selected=list(selected.definitions_en),
            action=decision.definitions_action,
        )
        next_examples = _apply_action(
            existing=existing_examples,
            selected=list(selected.examples_en),
            action=decision.examples_action,
        )

        update_fields: dict[str, str] = {}
        if not _same_values(existing_translations, next_translations):
            update_fields[fields.translation] = _format_translation_html(
                tuple(next_translations)
            )
        if not _same_values(existing_definitions, next_definitions):
            update_fields[fields.definitions_en] = _format_ranked_html(
                tuple(next_definitions), highlight_spec
            )
        if not _same_values(existing_examples, next_examples):
            update_fields[fields.example_en] = _format_ranked_html(
                tuple(next_examples), highlight_spec
            )
        return update_fields

    def _handle_add_result(
        self,
        future: Future[AnkiAddResult],
        on_done: Callable[[AnkiResult], None],
        on_unavailable: Callable[[], None] | None,
    ) -> None:
        if future.cancelled():
            return
        try:
            result = future.result()
        except Exception:
            on_done(AnkiResult(outcome=AnkiOutcome.ERROR, message=None))
            return
        if result.success:
            on_done(AnkiResult(outcome=AnkiOutcome.SUCCESS, message=None))
            return
        message = result.error or "Failed to add card."
        mapped = _result_for_error(message)
        if mapped.outcome is AnkiOutcome.UNAVAILABLE and on_unavailable is not None:
            on_unavailable()
        on_done(mapped)


def _values_from_result(result: TranslationResult) -> AnkiUpsertValues:
    translations = _dedupe_list(_parse_translation_values(result.translation_ru.text))
    definitions = _dedupe_list(list(result.definitions_en))
    examples = _dedupe_list([example.en for example in result.examples if example.en])
    return AnkiUpsertValues(
        translations=tuple(translations),
        definitions_en=tuple(definitions),
        examples_en=tuple(examples),
    )


def _selected_values(decision: AnkiUpsertDecision) -> AnkiUpsertValues:
    translations = _dedupe_list(list(decision.selected_translations))
    definitions = _dedupe_list(list(decision.selected_definitions_en))
    examples = _dedupe_list(list(decision.selected_examples_en))
    return AnkiUpsertValues(
        translations=tuple(translations),
        definitions_en=tuple(definitions),
        examples_en=tuple(examples),
    )


def _fallback_values(
    defaults: AnkiUpsertValues,
    selected: AnkiUpsertValues,
) -> AnkiUpsertValues:
    return AnkiUpsertValues(
        translations=selected.translations or defaults.translations,
        definitions_en=selected.definitions_en or defaults.definitions_en,
        examples_en=selected.examples_en or defaults.examples_en,
    )


def _build_deck_model_query(deck: str, model: str) -> str:
    escaped_deck = _query_escape(deck)
    escaped_model = _query_escape(model)
    return f'deck:"{escaped_deck}" note:"{escaped_model}"'


def _query_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _result_for_error(message: str) -> AnkiResult:
    cleaned = message.strip() or "Failed to process Anki request."
    lowered = cleaned.casefold()
    if "duplicate" in lowered:
        return AnkiResult(outcome=AnkiOutcome.DUPLICATE, message=cleaned)
    if "ankiconnect error" in lowered:
        return AnkiResult(outcome=AnkiOutcome.UNAVAILABLE, message=cleaned)
    return AnkiResult(outcome=AnkiOutcome.ERROR, message=cleaned)


def _apply_action(
    *,
    existing: list[str],
    selected: list[str],
    action: AnkiFieldAction,
) -> list[str]:
    if not selected:
        return list(existing)
    if action is AnkiFieldAction.KEEP_EXISTING:
        return list(existing)
    if action is AnkiFieldAction.REPLACE_WITH_SELECTED:
        return _dedupe_list(selected)
    return _merge_unique(existing, selected)


def _merge_unique(existing: list[str], selected: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *selected]:
        normalized = _normalize_token(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(_normalize_spaces(value))
    return merged


def _same_values(left: list[str], right: list[str]) -> bool:
    left_norm = [_normalize_token(value) for value in left if _normalize_token(value)]
    right_norm = [_normalize_token(value) for value in right if _normalize_token(value)]
    return left_norm == right_norm


def _dedupe_list(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized_value = _normalize_spaces(value)
        key = _normalize_token(normalized_value)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(normalized_value)
    return unique


def _parse_translation_values(raw: str) -> list[str]:
    normalized = _strip_html(raw)
    if not normalized:
        return []
    parts: list[str] = []
    for line in normalized.splitlines():
        stripped = _NUMBER_RE.sub("", line).strip()
        if not stripped:
            continue
        if ";" in stripped:
            for segment in stripped.split(";"):
                item = segment.strip()
                if item:
                    parts.append(item)
            continue
        parts.append(stripped)
    return _dedupe_list(parts)


def _parse_ranked_values(raw: str) -> list[str]:
    normalized = _strip_html(raw)
    if not normalized:
        return []
    items: list[str] = []
    for line in normalized.splitlines():
        stripped = _NUMBER_RE.sub("", line).strip()
        if stripped:
            items.append(stripped)
    return _dedupe_list(items)


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    value = _BR_RE.sub("\n", raw)
    value = _TAG_RE.sub("", value)
    value = html.unescape(value)
    return _normalize_spaces(value.replace("\r", "\n"))


def _normalize_spaces(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _normalize_token(value: str) -> str:
    return _normalize_spaces(value).casefold()


def _format_translation_html(values: tuple[str, ...]) -> str:
    cleaned = _dedupe_list(list(values))
    if not cleaned:
        return ""
    lines: list[str] = []
    for index, value in enumerate(cleaned, start=1):
        lines.append(f"{index}. {html.escape(value, quote=False)}")
    return "<br>".join(lines)


def _format_ranked_html(values: tuple[str, ...], highlight_spec: HighlightSpec) -> str:
    cleaned = _dedupe_list(list(values))
    if not cleaned:
        return ""
    lines: list[str] = []
    for index, value in enumerate(cleaned, start=1):
        highlighted = highlight_to_html_mark(value, highlight_spec, class_name="hl")
        lines.append(f"{index}. {highlighted}")
    return "<br>".join(lines)
