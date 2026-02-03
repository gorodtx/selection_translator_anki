from __future__ import annotations

from collections.abc import Iterator

from translate_logic.models import ExampleSource, VariantSource
from translate_logic.providers.reverso import (
    ReversoResult,
    ReversoClientProtocol,
    _translate_reverso_sync,
)


class DummyReversoClient(ReversoClientProtocol):
    def get_translations(
        self,
        text: str,
        source_lang: str | None = None,
        target_lang: str | None = None,
    ) -> Iterator[str]:
        return iter([" перевод1 ", "перевод1", "перевод2"])

    def get_translation_samples(
        self,
        text: str,
        target_text: str | None = None,
        source_lang: str | None = None,
        target_lang: str | None = None,
        cleanup: bool = True,
    ) -> Iterator[tuple[str, str]]:
        if target_text == "перевод1":
            return iter(
                [
                    ("Hello world", "Привет мир"),
                    ("Another example", "Другой пример"),
                    ("Extra", "Лишний"),
                ]
            )
        if target_text == "перевод2":
            return iter([("Sample", "Пример")])
        return iter([])


def test_translate_reverso_sync_builds_variants() -> None:
    result = _translate_reverso_sync(
        "hello",
        "en",
        "ru",
        max_variants=2,
        max_examples=2,
        client=DummyReversoClient(),
    )

    assert isinstance(result, ReversoResult)
    assert result.found is True
    assert [variant.ru for variant in result.variants] == ["перевод1", "перевод2"]
    assert result.variants[0].source is VariantSource.REVERSO
    assert result.variants[1].examples[0].source is ExampleSource.REVERSO
    assert len(result.variants[0].examples) == 2


def test_translate_reverso_sync_handles_empty_text() -> None:
    result = _translate_reverso_sync(
        "",
        "en",
        "ru",
        max_variants=2,
        max_examples=2,
        client=DummyReversoClient(),
    )
    assert result.found is False
    assert result.variants == ()
