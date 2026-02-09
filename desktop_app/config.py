from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Final

CONFIG_DIR_NAME: Final[str] = "translator"
CONFIG_FILE_NAME: Final[str] = "desktop_config.json"
DEFAULT_SOURCE_LANG: Final[str] = "en"
DEFAULT_TARGET_LANG: Final[str] = "ru"

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class LanguageConfig:
    source: str
    target: str


@dataclass(frozen=True, slots=True)
class AnkiFieldMap:
    word: str
    ipa: str
    translation: str
    example_en: str
    example_ru: str


@dataclass(frozen=True, slots=True)
class AnkiConfig:
    deck: str
    model: str
    fields: AnkiFieldMap


@dataclass(frozen=True, slots=True)
class AppConfig:
    languages: LanguageConfig
    anki: AnkiConfig


def config_path() -> Path:
    default_base = Path.home() / ".config"
    default_path = default_base / CONFIG_DIR_NAME / CONFIG_FILE_NAME
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    if not xdg_home:
        return default_path
    xdg_path = Path(xdg_home) / CONFIG_DIR_NAME / CONFIG_FILE_NAME
    if xdg_path.exists() and default_path.exists():
        try:
            if xdg_path.stat().st_mtime >= default_path.stat().st_mtime:
                return xdg_path
        except OSError:
            return xdg_path
        return default_path
    if xdg_path.exists():
        return xdg_path
    if default_path.exists():
        return default_path
    return xdg_path


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return _apply_env_overrides(_default_config())
    try:
        raw_data = path.read_text(encoding="utf-8")
        payload: JsonValue = json.loads(raw_data)
    except (OSError, json.JSONDecodeError):
        return _apply_env_overrides(_default_config())
    return _apply_env_overrides(_parse_config(payload))


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _config_to_dict(config)
    data = json.dumps(payload, ensure_ascii=True, indent=2)
    path.write_text(data, encoding="utf-8")


def _default_config() -> AppConfig:
    return AppConfig(
        languages=LanguageConfig(
            source=DEFAULT_SOURCE_LANG,
            target=DEFAULT_TARGET_LANG,
        ),
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


def _parse_config(payload: JsonValue) -> AppConfig:
    payload_dict = _get_dict(payload)
    if payload_dict is None:
        return _default_config()
    language_data = _get_dict(payload_dict.get("languages"))
    anki_data = _get_dict(payload_dict.get("anki"))
    fields_data = _get_dict(anki_data.get("fields")) if anki_data else None

    languages = LanguageConfig(
        source=_get_str(language_data.get("source"), DEFAULT_SOURCE_LANG)
        if language_data
        else DEFAULT_SOURCE_LANG,
        target=_get_str(language_data.get("target"), DEFAULT_TARGET_LANG)
        if language_data
        else DEFAULT_TARGET_LANG,
    )
    fields = AnkiFieldMap(
        word=_get_str(fields_data.get("word"), "") if fields_data else "",
        ipa=_get_str(fields_data.get("ipa"), "") if fields_data else "",
        translation=_get_str(fields_data.get("translation"), "") if fields_data else "",
        example_en=_get_str(fields_data.get("example_en"), "") if fields_data else "",
        example_ru=_get_str(fields_data.get("example_ru"), "") if fields_data else "",
    )
    anki = AnkiConfig(
        deck=_get_str(anki_data.get("deck"), "") if anki_data else "",
        model=_get_str(anki_data.get("model"), "") if anki_data else "",
        fields=fields,
    )
    return AppConfig(
        languages=languages,
        anki=anki,
    )


def _apply_env_overrides(config: AppConfig) -> AppConfig:
    if os.environ.get("TRANSLATOR_RESET", "").strip() != "1":
        return config
    return _default_config()


def _config_to_dict(config: AppConfig) -> dict[str, JsonValue]:
    return {
        "languages": {
            "source": config.languages.source,
            "target": config.languages.target,
        },
        "anki": {
            "deck": config.anki.deck,
            "model": config.anki.model,
            "fields": {
                "word": config.anki.fields.word,
                "ipa": config.anki.fields.ipa,
                "translation": config.anki.fields.translation,
                "example_en": config.anki.fields.example_en,
                "example_ru": config.anki.fields.example_ru,
            },
        },
    }


def _get_dict(value: JsonValue | None) -> dict[str, JsonValue] | None:
    if isinstance(value, dict):
        return value
    return None


def _get_str(value: JsonValue | None, default: str) -> str:
    if isinstance(value, str):
        return value
    return default
