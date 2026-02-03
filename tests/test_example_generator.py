from __future__ import annotations

from translate_logic.models import ExampleSource
from translate_logic.providers.example_generator import (
    ExampleGenerator,
    ExampleGeneratorService,
)


def test_example_generator_parses_json() -> None:
    def gen(prompt: str) -> str:
        return (
            '{"examples": ['
            '{"en": "Hello word", "ru": "Привет слово"},'
            '{"en": "Another word", "ru": "Другое слово"}]}'
        )

    generator = ExampleGenerator(generator=gen, max_examples=2)
    result = generator.generate("word", "слово")

    assert len(result.examples) == 2
    assert result.examples[0].source is ExampleSource.MT0


def test_example_generator_filters_translation_mismatch() -> None:
    def gen(prompt: str) -> str:
        return (
            '{"examples": ['
            '{"en": "Hello", "ru": "Привет"},'
            '{"en": "Word", "ru": "Слово"}]}'
        )

    generator = ExampleGenerator(generator=gen, max_examples=2)
    result = generator.generate("word", "слово")

    assert len(result.examples) == 1
    assert result.examples[0].ru == "Слово"


def test_example_generator_fallback_when_empty() -> None:
    def gen(prompt: str) -> str:
        return "not json"

    service = ExampleGeneratorService(generator=ExampleGenerator(generator=gen))
    result = service.generate("word", "слово")

    assert len(result.examples) == 2
    assert all(example.source is ExampleSource.FALLBACK for example in result.examples)
