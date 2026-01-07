from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
from typing import Final

CONFIG_DIR_NAME: Final[str] = "translator"
CONFIG_FILE_NAME: Final[str] = "desktop_config.json"
DEFAULT_SOURCE_LANG: Final[str] = "en"
DEFAULT_TARGET_LANG: Final[str] = "ru"
DEFAULT_HOTKEY_TRIGGER: Final[str] = "Ctrl+Alt+T"


class HotkeyBackend(Enum):
    SYSTEM = "system"
    PORTAL = "portal"
    X11 = "x11"
    GNOME = "gnome"


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
class HotkeyConfig:
    backend: HotkeyBackend
    trigger: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    languages: LanguageConfig
    anki: AnkiConfig
    hotkey: HotkeyConfig
    autostart_prompted: bool
    autostart_enabled: bool
    ready_notified: bool


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
        return _default_config()
    try:
        raw_data = path.read_text(encoding="utf-8")
        payload: object = json.loads(raw_data)
    except (OSError, json.JSONDecodeError):
        return _default_config()
    return _parse_config(payload)


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
        hotkey=HotkeyConfig(
            backend=_default_hotkey_backend(),
            trigger=DEFAULT_HOTKEY_TRIGGER,
        ),
        autostart_prompted=False,
        autostart_enabled=False,
        ready_notified=False,
    )


def _parse_config(payload: object) -> AppConfig:
    payload_dict = _get_dict(payload)
    if payload_dict is None:
        return _default_config()
    language_data = _get_dict(payload_dict.get("languages"))
    anki_data = _get_dict(payload_dict.get("anki"))
    hotkey_data = _get_dict(payload_dict.get("hotkey"))
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
    hotkey = HotkeyConfig(
        backend=_get_hotkey_backend(
            hotkey_data.get("backend") if hotkey_data else None,
            _default_hotkey_backend(),
        ),
        trigger=_get_str(
            hotkey_data.get("trigger") if hotkey_data else None,
            DEFAULT_HOTKEY_TRIGGER,
        ),
    )
    return AppConfig(
        languages=languages,
        anki=anki,
        hotkey=hotkey,
        autostart_prompted=_get_bool(payload_dict.get("autostart_prompted"), False),
        autostart_enabled=_get_bool(payload_dict.get("autostart_enabled"), False),
        ready_notified=_get_bool(payload_dict.get("ready_notified"), False),
    )


def _config_to_dict(config: AppConfig) -> dict[str, object]:
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
        "hotkey": {
            "backend": config.hotkey.backend.value,
            "trigger": config.hotkey.trigger,
        },
        "autostart_prompted": config.autostart_prompted,
        "autostart_enabled": config.autostart_enabled,
        "ready_notified": config.ready_notified,
    }


def _get_dict(value: object | None) -> dict[str, object] | None:
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for raw_key, raw_item in value.items():
            if isinstance(raw_key, str):
                key: str = raw_key
                item: object = raw_item
                output[key] = item
        return output
    return None


def _get_str(value: object | None, default: str) -> str:
    if isinstance(value, str):
        return value
    return default


def _get_bool(value: object | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _default_hotkey_backend() -> HotkeyBackend:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").casefold()
    if "gnome" in desktop:
        return HotkeyBackend.GNOME
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" or "WAYLAND_DISPLAY" in os.environ:
        return HotkeyBackend.PORTAL
    if os.environ.get("DISPLAY"):
        return HotkeyBackend.X11
    return HotkeyBackend.SYSTEM


def detect_hotkey_backend() -> HotkeyBackend:
    return _default_hotkey_backend()


def _get_hotkey_backend(value: object | None, default: HotkeyBackend) -> HotkeyBackend:
    if isinstance(value, str):
        for backend in HotkeyBackend:
            if backend.value == value:
                return backend
    return default
