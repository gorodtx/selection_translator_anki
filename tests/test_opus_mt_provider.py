from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from translate_logic.providers.opus_mt import (
    OpusMtModel,
    OpusMtPair,
    OpusMtProvider,
)


@dataclass(frozen=True, slots=True)
class DummyTokenizer:
    decoded: str

    def __call__(
        self, text: str, return_tensors: str, **kwargs: object
    ) -> dict[str, object]:
        return {"input_ids": [1, 2, 3]}

    def decode(
        self, token_ids: Sequence[int] | object, skip_special_tokens: bool = True
    ) -> str:
        return self.decoded


@dataclass(frozen=True, slots=True)
class DummyModel:
    output: Sequence[Sequence[int]]

    def generate(self, **kwargs: object) -> Sequence[Sequence[int]]:
        return self.output


@dataclass(slots=True)
class DummyLoader:
    last_model: OpusMtModel | None = None

    def __call__(self, model: OpusMtModel, cache_dir: Path | None) -> OpusMtPair:
        self.last_model = model
        return OpusMtPair(
            tokenizer=DummyTokenizer(decoded=" result "),
            model=DummyModel(output=[[1, 2]]),
        )


def test_opus_mt_provider_translates_and_trims() -> None:
    loader = DummyLoader()
    provider = OpusMtProvider(model_dir=Path("/tmp"), loader=loader)

    result = provider.translate("hello", "en", "ru")

    assert result == "result"
    assert loader.last_model is OpusMtModel.EN_RU


def test_opus_mt_provider_returns_none_for_unsupported_language() -> None:
    loader = DummyLoader()
    provider = OpusMtProvider(loader=loader)

    result = provider.translate("hello", "de", "ru")

    assert result is None
    assert loader.last_model is None


def test_opus_mt_provider_returns_none_for_empty_text() -> None:
    loader = DummyLoader()
    provider = OpusMtProvider(loader=loader)

    result = provider.translate("   ", "en", "ru")

    assert result is None
    assert loader.last_model is None
