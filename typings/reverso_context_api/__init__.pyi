from __future__ import annotations

from collections.abc import Iterator

class ReversoException(Exception):
    context: dict[str, object]

    def __init__(self, error: object, **context: object) -> None: ...

class Client:
    def __init__(
        self,
        source_lang: str,
        target_lang: str,
        credentials: tuple[str, str] | None = ...,
        user_agent: str | None = ...,
    ) -> None: ...
    def get_translations(
        self,
        text: str,
        source_lang: str | None = ...,
        target_lang: str | None = ...,
    ) -> Iterator[str]: ...
    def get_translation_samples(
        self,
        text: str,
        target_text: str | None = ...,
        source_lang: str | None = ...,
        target_lang: str | None = ...,
        cleanup: bool = ...,
    ) -> Iterator[tuple[str, str]]: ...
    def get_favorites(
        self,
        source_lang: str | None = ...,
        target_lang: str | None = ...,
        cleanup: bool = ...,
    ) -> Iterator[dict[str, str]]: ...
    def get_search_suggestions(
        self,
        text: str,
        source_lang: str | None = ...,
        target_lang: str | None = ...,
        fuzzy_search: bool = ...,
        cleanup: bool = ...,
    ) -> Iterator[str]: ...
