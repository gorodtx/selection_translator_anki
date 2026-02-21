from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
import hashlib
import html
from pathlib import Path
import re

from desktop_app.infrastructure.anki import (
    AnkiAddResult,
    AnkiCreateModelResult,
    AnkiIdListResult,
    AnkiListResult,
    AnkiNoteDetailsResult,
    AnkiUpdateResult,
)
from desktop_app.application.use_cases.anki_upsert import (
    AnkiFieldAction,
    AnkiImageAction,
    AnkiUpsertDecision,
    AnkiUpsertMatch,
    AnkiUpsertPreview,
    AnkiUpsertValues,
)
from desktop_app.application.ports.interfaces import AnkiPort
from desktop_app.config import AnkiConfig, AnkiFieldMap
from translate_logic.shared.highlight import (
    HighlightSpec,
    build_highlight_spec,
    highlight_to_html_mark,
)
from translate_logic.models import TranslationResult

_WHITESPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_NUMBER_RE = re.compile(r"^\s*\d+\.\s*")
_NON_FILE_CHARS_RE = re.compile(r"[^a-z0-9._-]+")
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class PreparedImage:
    local_path: str
    media_filename: str
    html_tag: str


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
                fields.image,
            ]
        )

    def build_fields(
        self, config: AnkiConfig, original_text: str, result: TranslationResult
    ) -> dict[str, str]:
        values = _values_from_result(result)
        return self._build_fields_from_values(
            config,
            original_text,
            values,
            field_map=config.fields,
        )

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
        expected_fields = _required_field_names(config.fields)

        def _fallback_preview() -> AnkiUpsertPreviewResult:
            return AnkiUpsertPreviewResult(
                preview=AnkiUpsertPreview(
                    values=values,
                    matches=(),
                    available_fields=expected_fields,
                ),
                error=None,
            )

        def _finish(payload: AnkiUpsertPreviewResult) -> None:
            if completion.cancelled() or completion.done():
                return
            completion.set_result(payload)

        def _start_find() -> None:
            query = _build_deck_model_query(config.deck, config.model)
            find_future = self.service.find_notes(query)

            def _on_find(done: Future[AnkiIdListResult]) -> None:
                if completion.cancelled() or completion.done():
                    return
                if done.cancelled():
                    completion.cancel()
                    return
                try:
                    find_result = done.result()
                except Exception as exc:
                    del exc
                    _finish(_fallback_preview())
                    return
                if find_result.error is not None:
                    _finish(_fallback_preview())
                    return
                note_ids = find_result.items
                if not note_ids:
                    _finish(
                        AnkiUpsertPreviewResult(
                            preview=AnkiUpsertPreview(
                                values=values,
                                matches=(),
                                available_fields=expected_fields,
                            ),
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
                        del exc
                        _finish(_fallback_preview())
                        return
                    if details_result.error is not None:
                        _finish(_fallback_preview())
                        return
                    available_fields = _merge_available_fields(
                        expected_fields,
                        _collect_available_fields(details_result.items),
                    )
                    normalized_word = _normalize_token(original_text)
                    matches: list[AnkiUpsertMatch] = []
                    for details in details_result.items:
                        stored_word = details.fields.get(config.fields.word, "")
                        if (
                            _normalize_token(_strip_html(stored_word))
                            != normalized_word
                        ):
                            continue
                        matches.append(
                            AnkiUpsertMatch(
                                note_id=details.note_id,
                                word=stored_word,
                                translation=details.fields.get(
                                    config.fields.translation, ""
                                ),
                                definitions_en=details.fields.get(
                                    config.fields.definitions_en, ""
                                ),
                                examples_en=details.fields.get(
                                    config.fields.example_en, ""
                                ),
                                image=details.fields.get(config.fields.image, ""),
                            )
                        )
                    _finish(
                        AnkiUpsertPreviewResult(
                            preview=AnkiUpsertPreview(
                                values=values,
                                matches=tuple(matches),
                                available_fields=available_fields,
                            ),
                            error=None,
                        )
                    )

                details_future.add_done_callback(_on_details)

            find_future.add_done_callback(_on_find)

        _start_find()
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
        selected_values = _fill_merge_defaults(
            selected=selected_values,
            defaults=preview.values,
            decision=decision,
        )
        effective_field_map = config.fields
        should_store_image = bool(decision.image_path) and (
            decision.create_new
            or not decision.target_note_ids
            or decision.image_action is AnkiImageAction.REPLACE_WITH_SELECTED
        )
        prepared_image, image_error = _prepare_image_for_upsert(
            original_text=original_text,
            image_path=decision.image_path if should_store_image else None,
        )
        if image_error is not None:
            completion.set_result(_result_for_error(image_error))
            return completion

        def _apply_with_image(image_html: str | None) -> None:
            if decision.create_new or not decision.target_note_ids:
                create_values = _fallback_values(preview.values, selected_values)
                fields = self._build_fields_from_values(
                    config,
                    original_text,
                    create_values,
                    field_map=effective_field_map,
                    image_html=image_html,
                )
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
                return

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
                    field_map=effective_field_map,
                    image_html=image_html,
                )
                if update_fields:
                    updates.append((note_id, update_fields))

            if not updates:
                completion.set_result(AnkiResult(outcome=AnkiOutcome.UNCHANGED))
                return

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
                            failures.append(
                                update_result.error or "Failed to update card."
                            )
                    except Exception as exc:
                        failures.append(str(exc) or "Failed to update card.")
                pending -= 1
                if pending <= 0:
                    _done()

            for note_id, fields in updates:
                update_future = self.service.update_note_fields(note_id, fields)
                update_future.add_done_callback(_on_update)

        if prepared_image is None:
            _apply_with_image(None)
            return completion

        media_future = self.service.store_media_path(
            prepared_image.local_path,
            prepared_image.media_filename,
        )

        def _on_media_stored(done: Future[AnkiUpdateResult]) -> None:
            if completion.cancelled() or completion.done():
                return
            if done.cancelled():
                completion.cancel()
                return
            try:
                result = done.result()
            except Exception as exc:
                completion.set_result(
                    _result_for_error(str(exc) or "Failed to store image.")
                )
                return
            if not result.success:
                completion.set_result(
                    _result_for_error(result.error or "Failed to store image.")
                )
                return
            _apply_with_image(prepared_image.html_tag)

        media_future.add_done_callback(_on_media_stored)
        return completion

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front: str,
        back: str,
        css: str,
    ) -> Future[AnkiCreateModelResult]:
        completion: Future[AnkiCreateModelResult] = Future()
        model_names_future = self.service.model_names()

        def _set_result(result: AnkiCreateModelResult) -> None:
            if completion.cancelled() or completion.done():
                return
            completion.set_result(result)

        def _start_create() -> None:
            create_future = self.service.create_model(
                model_name, fields, front, back, css
            )

            def _on_create(done_create: Future[AnkiCreateModelResult]) -> None:
                if completion.cancelled() or completion.done():
                    return
                if done_create.cancelled():
                    completion.cancel()
                    return
                try:
                    create_result = done_create.result()
                except Exception as exc:
                    _set_result(
                        AnkiCreateModelResult(
                            success=False,
                            error=str(exc) or "Failed to create Anki model.",
                        )
                    )
                    return
                _set_result(create_result)

            create_future.add_done_callback(_on_create)

        def _delete_models(candidates: list[str]) -> None:
            if completion.cancelled() or completion.done():
                return
            if not candidates:
                _start_create()
                return
            model_to_delete = candidates.pop(0)
            delete_future = self.service.delete_model(model_to_delete)

            def _on_delete(done_delete: Future[AnkiUpdateResult]) -> None:
                if completion.cancelled() or completion.done():
                    return
                if done_delete.cancelled():
                    completion.cancel()
                    return
                try:
                    delete_result = done_delete.result()
                except Exception as exc:
                    _set_result(
                        AnkiCreateModelResult(
                            success=False,
                            error=str(exc) or "Failed to delete legacy Anki model.",
                        )
                    )
                    return
                if not delete_result.success:
                    message = (
                        delete_result.error or "Failed to delete legacy Anki model."
                    )
                    if not _is_delete_model_non_fatal(message):
                        _set_result(AnkiCreateModelResult(success=False, error=message))
                        return
                _delete_models(candidates)

            delete_future.add_done_callback(_on_delete)

        def _on_model_names(done_names: Future[AnkiListResult]) -> None:
            if completion.cancelled() or completion.done():
                return
            if done_names.cancelled():
                completion.cancel()
                return
            try:
                names_result = done_names.result()
            except Exception as exc:
                _set_result(
                    AnkiCreateModelResult(
                        success=False,
                        error=str(exc) or "Failed to list Anki models.",
                    )
                )
                return
            if names_result.error is not None:
                _set_result(
                    AnkiCreateModelResult(success=False, error=names_result.error)
                )
                return
            delete_candidates = _owned_models_for_cleanup(
                names_result.items, model_name
            )
            _delete_models(delete_candidates)

        model_names_future.add_done_callback(_on_model_names)
        return completion

    def _build_fields_from_values(
        self,
        config: AnkiConfig,
        original_text: str,
        values: AnkiUpsertValues,
        field_map: AnkiFieldMap,
        image_html: str | None = None,
    ) -> dict[str, str]:
        fields = field_map
        highlight_spec = build_highlight_spec(original_text)
        payload: dict[str, str] = {fields.word: original_text}
        payload[fields.translation] = _format_translation_html(values.translations)
        payload[fields.definitions_en] = _format_definitions_html(
            values.definitions_en, highlight_spec
        )
        payload[fields.example_en] = _format_ranked_html(
            values.examples_en, highlight_spec
        )
        if fields.image.strip() and image_html is not None:
            payload[fields.image] = image_html
        return payload

    def _build_update_fields(
        self,
        *,
        config: AnkiConfig,
        original_text: str,
        match: AnkiUpsertMatch,
        decision: AnkiUpsertDecision,
        selected: AnkiUpsertValues,
        field_map: AnkiFieldMap,
        image_html: str | None = None,
    ) -> dict[str, str]:
        fields = field_map
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
            update_fields[fields.definitions_en] = _format_definitions_html(
                tuple(next_definitions), highlight_spec
            )
        if not _same_values(existing_examples, next_examples):
            update_fields[fields.example_en] = _format_ranked_html(
                tuple(next_examples), highlight_spec
            )
        if (
            fields.image.strip()
            and image_html is not None
            and decision.image_action is AnkiImageAction.REPLACE_WITH_SELECTED
        ):
            existing_image = _normalize_spaces(match.image)
            incoming_image = _normalize_spaces(image_html)
            if incoming_image and existing_image != incoming_image:
                update_fields[fields.image] = image_html
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
        image_path=None,
    )


def _selected_values(decision: AnkiUpsertDecision) -> AnkiUpsertValues:
    translations = _dedupe_list(list(decision.selected_translations))
    definitions = _dedupe_list(list(decision.selected_definitions_en))
    examples = _dedupe_list(list(decision.selected_examples_en))
    return AnkiUpsertValues(
        translations=tuple(translations),
        definitions_en=tuple(definitions),
        examples_en=tuple(examples),
        image_path=decision.image_path,
    )


def _fallback_values(
    defaults: AnkiUpsertValues,
    selected: AnkiUpsertValues,
) -> AnkiUpsertValues:
    return AnkiUpsertValues(
        translations=selected.translations or defaults.translations,
        definitions_en=selected.definitions_en or defaults.definitions_en,
        examples_en=selected.examples_en or defaults.examples_en,
        image_path=selected.image_path or defaults.image_path,
    )


def _fill_merge_defaults(
    *,
    selected: AnkiUpsertValues,
    defaults: AnkiUpsertValues,
    decision: AnkiUpsertDecision,
) -> AnkiUpsertValues:
    translations = selected.translations
    definitions = selected.definitions_en
    examples = selected.examples_en
    if (
        decision.translation_action is AnkiFieldAction.MERGE_UNIQUE_SELECTED
        and not translations
    ):
        translations = defaults.translations
    if (
        decision.definitions_action is AnkiFieldAction.MERGE_UNIQUE_SELECTED
        and not definitions
    ):
        definitions = defaults.definitions_en
    if (
        decision.examples_action is AnkiFieldAction.MERGE_UNIQUE_SELECTED
        and not examples
    ):
        examples = defaults.examples_en
    return AnkiUpsertValues(
        translations=translations,
        definitions_en=definitions,
        examples_en=examples,
        image_path=selected.image_path or defaults.image_path,
    )


def _collect_available_fields(details: Sequence[object]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for item in details:
        fields = getattr(item, "fields", None)
        if not isinstance(fields, dict):
            continue
        for field_name in fields.keys():
            if not isinstance(field_name, str):
                continue
            normalized = field_name.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            names.append(field_name)
    return tuple(names)


def _merge_available_fields(*groups: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for field_name in group:
            cleaned = field_name.strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
    return tuple(merged)


def _required_field_names(fields: AnkiFieldMap) -> tuple[str, ...]:
    required = (
        fields.word.strip(),
        fields.translation.strip(),
        fields.example_en.strip(),
        fields.definitions_en.strip(),
        fields.image.strip(),
    )
    return tuple(value for value in required if value)


def _owned_models_for_cleanup(model_names: list[str], target_model: str) -> list[str]:
    target = target_model.strip()
    if not target:
        return []
    target_key = target.casefold()
    owned: list[str] = []
    for model_name in model_names:
        cleaned = model_name.strip()
        if not cleaned:
            continue
        lowered = cleaned.casefold()
        if lowered == target_key or lowered.startswith(f"{target_key} "):
            owned.append(cleaned)
    return list(dict.fromkeys(owned))


def _is_delete_model_non_fatal(message: str) -> bool:
    lowered = message.casefold()
    return (
        "does not exist" in lowered
        or "model was not found" in lowered
        or "no such model" in lowered
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
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if ";" in stripped_line:
            for segment in stripped_line.split(";"):
                stripped = _NUMBER_RE.sub("", segment).strip()
                if stripped.startswith(":"):
                    stripped = stripped[1:].strip()
                if stripped:
                    items.append(stripped)
            continue
        stripped = _NUMBER_RE.sub("", stripped_line).strip()
        if stripped.startswith(":"):
            stripped = stripped[1:].strip()
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


def _prepare_image_for_upsert(
    *, original_text: str, image_path: str | None
) -> tuple[PreparedImage | None, str | None]:
    if not image_path:
        return None, None
    path = Path(image_path).expanduser()
    try:
        stat = path.stat()
    except OSError:
        return None, "Image file is not accessible."
    if not path.is_file():
        return None, "Image path is not a file."
    extension = path.suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return None, "Unsupported image format."
    if stat.st_size <= 0:
        return None, "Image file is empty."
    if stat.st_size > _MAX_IMAGE_BYTES:
        return None, "Image file is too large (max 5 MB)."
    base = _normalize_token(original_text) or _normalize_token(path.stem) or "image"
    safe_base = _NON_FILE_CHARS_RE.sub("_", base).strip("._-")
    if not safe_base:
        safe_base = "image"
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    digest_source = f"{resolved}:{stat.st_mtime_ns}:{stat.st_size}"
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    media_filename = f"{safe_base[:40]}_{digest}{extension}"
    alt = html.escape(_normalize_spaces(original_text) or "image", quote=True)
    src = html.escape(media_filename, quote=True)
    html_tag = f'<img src="{src}" alt="{alt}">'
    return (
        PreparedImage(
            local_path=str(path),
            media_filename=media_filename,
            html_tag=html_tag,
        ),
        None,
    )


def _format_translation_html(values: tuple[str, ...]) -> str:
    cleaned = _dedupe_list(list(values))
    if not cleaned:
        return ""
    return "; ".join(html.escape(value, quote=False) for value in cleaned)


def _format_ranked_html(values: tuple[str, ...], highlight_spec: HighlightSpec) -> str:
    cleaned = _dedupe_list(list(values))
    if not cleaned:
        return ""
    lines = [
        highlight_to_html_mark(value, highlight_spec, class_name="hl")
        for value in cleaned
    ]
    return "<br>".join(lines)


def _format_definitions_html(
    values: tuple[str, ...], highlight_spec: HighlightSpec
) -> str:
    cleaned = _dedupe_list(list(values))
    if not cleaned:
        return ""
    lines: list[str] = []
    for value in cleaned:
        highlighted = highlight_to_html_mark(value, highlight_spec, class_name="hl")
        lines.append(highlighted)
    rendered: list[str] = []
    for index, line in enumerate(lines):
        if index < len(lines) - 1:
            rendered.append(f"{line};")
        else:
            rendered.append(line)
    return f"<i>{'<br>'.join(rendered)}</i>"
