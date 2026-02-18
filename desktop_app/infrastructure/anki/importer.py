from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile
from typing import TypeGuard

from desktop_app.infrastructure.anki.field_hints import score_field_match


@dataclass(frozen=True, slots=True)
class DeckImportResult:
    deck: str
    model: str
    fields: list[str]
    error: str | None


@dataclass(frozen=True, slots=True)
class DeckInfo:
    deck_id: int
    name: str
    model_id: int | None


@dataclass(frozen=True, slots=True)
class ModelInfo:
    model_id: int
    name: str
    fields: list[str]


def import_deck(path: Path) -> DeckImportResult:
    if not path.exists():
        return DeckImportResult(deck="", model="", fields=[], error="Deck not found.")
    try:
        collection_name, db_bytes = _extract_collection(path)
    except DeckImportError as exc:
        return DeckImportResult(deck="", model="", fields=[], error=str(exc))
    if db_bytes is None:
        return DeckImportResult(
            deck="", model="", fields=[], error="Deck has no collection database."
        )
    temp_path = None
    try:
        temp_path = _write_temp_db(db_bytes, suffix=collection_name)
        deck_json, model_json = _read_col_json(temp_path)
        decks = _coerce_dict(_load_json(deck_json))
        models = _coerce_dict(_load_json(model_json))
        if decks is None or models is None:
            return DeckImportResult(
                deck="", model="", fields=[], error="Deck metadata is invalid."
            )
        deck_info = _select_deck(decks)
        if deck_info is None:
            return DeckImportResult(
                deck="", model="", fields=[], error="No deck found."
            )
        model_ids = _select_model_ids_from_deck(temp_path, deck_info.deck_id)
        if model_ids:
            model_info = _select_best_model(models, model_ids)
        else:
            model_info = _select_model(models, deck_info.model_id)
        if model_info is None:
            return DeckImportResult(
                deck="", model="", fields=[], error="No model found."
            )
        return DeckImportResult(
            deck=deck_info.name,
            model=model_info.name,
            fields=model_info.fields,
            error=None,
        )
    except DeckImportError as exc:
        return DeckImportResult(deck="", model="", fields=[], error=str(exc))
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


class DeckImportError(Exception):
    pass


def _extract_collection(path: Path) -> tuple[str, bytes | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            collection_name = _select_collection_name(archive.namelist())
            if collection_name is None:
                raise DeckImportError("Deck archive has no collection database.")
            with archive.open(collection_name) as handle:
                data = handle.read()
            return collection_name, data
    except zipfile.BadZipFile as exc:
        raise DeckImportError("Deck file is not a valid .apkg archive.") from exc
    except OSError as exc:
        raise DeckImportError("Failed to read deck archive.") from exc


def _select_collection_name(names: list[str]) -> str | None:
    if "collection.anki2" in names:
        return "collection.anki2"
    if "collection.anki21" in names:
        return "collection.anki21"
    return None


def _write_temp_db(data: bytes, suffix: str) -> str:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(data)
            return handle.name
    except OSError as exc:
        raise DeckImportError("Failed to write deck database.") from exc


def _read_col_json(path: str) -> tuple[str, str]:
    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise DeckImportError("Failed to read deck database.") from exc
    try:
        row = connection.execute("SELECT decks, models FROM col LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise DeckImportError("Deck database is unreadable.") from exc
    finally:
        connection.close()
    if row is None:
        raise DeckImportError("Deck database is empty.")
    decks, models = row
    if not isinstance(decks, str) or not isinstance(models, str):
        raise DeckImportError("Deck metadata is invalid.")
    return decks, models


def _load_json(data: str) -> object:
    try:
        return json.loads(data)
    except json.JSONDecodeError as exc:
        raise DeckImportError("Deck metadata is invalid.") from exc


def _coerce_dict(value: object) -> dict[str, object] | None:
    if _is_str_dict(value):
        return dict(value)
    return None


def _coerce_list(value: object) -> list[object] | None:
    if _is_object_list(value):
        return list(value)
    return None


def _coerce_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _select_deck(decks: dict[str, object]) -> DeckInfo | None:
    candidates: list[DeckInfo] = []
    for raw_key, raw_item in decks.items():
        deck_id = _coerce_int(raw_key)
        if deck_id is None:
            continue
        info = _parse_deck_info(deck_id, raw_item)
        if info is None:
            continue
        candidates.append(info)
    if not candidates:
        return None
    non_default = [deck for deck in candidates if deck.name.casefold() != "default"]
    if non_default:
        return non_default[0]
    return candidates[0]


def _parse_deck_info(deck_id: int, value: object) -> DeckInfo | None:
    deck_dict = _coerce_dict(value)
    if deck_dict is None:
        return None
    name = _coerce_str(deck_dict.get("name"))
    if name is None or not name.strip():
        return None
    dyn = _coerce_int(deck_dict.get("dyn"))
    if dyn == 1:
        return None
    model_id = _coerce_int(deck_dict.get("mid"))
    return DeckInfo(deck_id=deck_id, name=name.strip(), model_id=model_id)


def _select_model_ids_from_deck(path: str, deck_id: int) -> list[int]:
    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            "SELECT DISTINCT notes.mid "
            "FROM cards "
            "JOIN notes ON cards.nid = notes.id "
            "WHERE cards.did = ?",
            (deck_id,),
        ).fetchall()
        mids: list[int] = []
        for row in rows:
            if not row:
                continue
            mid = _coerce_int(row[0])
            if mid is not None:
                mids.append(mid)
        return mids
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def _select_model(models: dict[str, object], model_id: int | None) -> ModelInfo | None:
    parsed: list[ModelInfo] = []
    for item in models.values():
        info = _parse_model_info(item)
        if info is None:
            continue
        parsed.append(info)
    if not parsed:
        return None
    if model_id is not None:
        for info in parsed:
            if info.model_id == model_id:
                return info
    return parsed[0]


def _select_best_model(
    models: dict[str, object],
    model_ids: list[int],
) -> ModelInfo | None:
    parsed: list[ModelInfo] = []
    for item in models.values():
        info = _parse_model_info(item)
        if info is None:
            continue
        parsed.append(info)
    if not parsed:
        return None
    model_set = set(model_ids)
    candidates = [info for info in parsed if info.model_id in model_set]
    if not candidates:
        candidates = parsed
    best = candidates[0]
    best_score = score_field_match(best.fields)
    for info in candidates[1:]:
        score = score_field_match(info.fields)
        if score > best_score:
            best = info
            best_score = score
    return best


def _parse_model_info(value: object) -> ModelInfo | None:
    model_dict = _coerce_dict(value)
    if model_dict is None:
        return None
    model_id = _coerce_int(model_dict.get("id"))
    name = _coerce_str(model_dict.get("name"))
    raw_fields = _coerce_list(model_dict.get("flds"))
    if model_id is None or name is None or raw_fields is None:
        return None
    fields: list[str] = []
    for entry in raw_fields:
        entry_dict = _coerce_dict(entry)
        if entry_dict is None:
            continue
        field_name = _coerce_str(entry_dict.get("name"))
        if field_name is None or not field_name.strip():
            continue
        fields.append(field_name.strip())
    return ModelInfo(model_id=model_id, name=name, fields=fields)
