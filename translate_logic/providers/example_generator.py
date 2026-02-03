from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from translate_logic.models import ExamplePair, ExampleSource


class ExampleGeneratorError(Enum):
    TIMEOUT = "timeout"
    INVALID_JSON = "invalid_json"
    EMPTY = "empty"


class ExampleGeneratorModel(Protocol):
    def generate(self, **kwargs: object) -> list[list[int]]: ...


class ExampleGeneratorTokenizer(Protocol):
    def __call__(
        self,
        text: str,
        return_tensors: str,
        **kwargs: object,
    ) -> dict[str, object]: ...

    def decode(self, output: list[int], skip_special_tokens: bool = True) -> str: ...


GeneratorFn = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class ExampleGeneration:
    examples: tuple[ExamplePair, ...]
    error: ExampleGeneratorError | None


@dataclass(slots=True)
class ExampleGenerator:
    generator: GeneratorFn
    max_examples: int = 2

    def generate(self, word: str, translation: str) -> ExampleGeneration:
        prompt = _build_prompt(word, translation, self.max_examples)
        try:
            raw = self.generator(prompt)
        except TimeoutError:
            return ExampleGeneration(examples=(), error=ExampleGeneratorError.TIMEOUT)
        except Exception:
            return ExampleGeneration(examples=(), error=ExampleGeneratorError.EMPTY)
        parsed, error = _extract_examples(raw, translation)
        if not parsed:
            return ExampleGeneration(examples=(), error=error)
        return ExampleGeneration(examples=parsed, error=None)


@dataclass(slots=True)
class Mt0ExampleGenerator:
    tokenizer: ExampleGeneratorTokenizer
    model: ExampleGeneratorModel
    max_new_tokens: int = 128
    temperature: float = 0.3

    def __call__(self, prompt: str) -> str:
        encoded = self.tokenizer(prompt, return_tensors="pt")
        outputs = self.model.generate(
            **encoded,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
        )
        if not outputs:
            return ""
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)


@dataclass(slots=True)
class ExampleGeneratorService:
    generator: ExampleGenerator
    fallback_builder: Callable[[str, str], tuple[ExamplePair, ...]] = field(
        default_factory=lambda: _fallback_examples
    )

    def generate(self, word: str, translation: str) -> ExampleGeneration:
        result = self.generator.generate(word, translation)
        if result.examples:
            return result
        return ExampleGeneration(
            examples=self.fallback_builder(word, translation),
            error=result.error,
        )


@dataclass(frozen=True, slots=True)
class ExamplePayload:
    en: str
    ru: str


_PROMPT_TEMPLATE = (
    "Generate {count} short English sentences that contain the word or phrase "
    '"{word}". Translate each sentence into Russian using the exact translation '
    '"{translation}". Respond strictly in JSON format: {{"examples": '
    '[{{"en": "...", "ru": "..."}}, ...]}}.'
)


def _build_prompt(word: str, translation: str, count: int) -> str:
    return _PROMPT_TEMPLATE.format(word=word, translation=translation, count=count)


def _extract_examples(
    raw: str, translation: str
) -> tuple[tuple[ExamplePair, ...], ExampleGeneratorError]:
    payload = _extract_payload(raw)
    if payload is None:
        return (), ExampleGeneratorError.INVALID_JSON
    examples: list[ExamplePair] = []
    translation_key = translation.strip().casefold()
    for item in payload:
        en = item.en.strip()
        ru = item.ru.strip()
        if not en or not ru:
            continue
        if translation_key not in ru.casefold():
            continue
        examples.append(ExamplePair(en=en, ru=ru, source=ExampleSource.MT0))
    if not examples:
        return (), ExampleGeneratorError.EMPTY
    return tuple(examples), ExampleGeneratorError.EMPTY


def _extract_payload(raw: str) -> list[ExamplePayload] | None:
    data = _load_json(raw)
    if data is None:
        return None
    raw_examples = data.get("examples")
    if not isinstance(raw_examples, list):
        return None
    parsed: list[ExamplePayload] = []
    for item in raw_examples:
        payload = _as_str_keyed_dict(item)
        if payload is None:
            continue
        en = payload.get("en")
        ru = payload.get("ru")
        if not isinstance(en, str) or not isinstance(ru, str):
            continue
        parsed.append(ExamplePayload(en=en, ru=ru))
    return parsed


def _load_json(raw: str) -> dict[str, object] | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match is None:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _as_str_keyed_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(key, str):
            result[key] = item
    return result


def _fallback_examples(word: str, translation: str) -> tuple[ExamplePair, ...]:
    return (
        ExamplePair(
            en=f"This is a {word}.",
            ru=f"Это {translation}.",
            source=ExampleSource.FALLBACK,
        ),
        ExamplePair(
            en=f"I see the {word}.",
            ru=f"Я вижу {translation}.",
            source=ExampleSource.FALLBACK,
        ),
    )
