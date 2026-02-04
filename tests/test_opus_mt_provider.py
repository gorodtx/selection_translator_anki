from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from translate_logic.providers.opus_mt import (
    Ct2TranslationResult,
    OpusMtPair,
    OpusMtPairKey,
    OpusMtProvider,
)


@dataclass(frozen=True, slots=True)
class DummySentencePiece:
    encoded: list[str]
    decoded: str

    def encode(self, text: str, out_type: type[str]) -> list[str]:
        return self.encoded

    def decode(self, pieces: Sequence[str]) -> str:
        return self.decoded


@dataclass(frozen=True, slots=True)
class DummyResult:
    hypotheses: Sequence[Sequence[str]]


@dataclass(slots=True)
class DummyTranslator:
    last_source: Sequence[Sequence[str]] | None = None

    def translate_batch(
        self,
        source: Sequence[Sequence[str]],
        *,
        beam_size: int,
        num_hypotheses: int,
        max_decoding_length: int,
        return_scores: bool,
    ) -> list[Ct2TranslationResult]:
        self.last_source = source
        return [DummyResult(hypotheses=[["x"], ["y"]][:num_hypotheses])]


@dataclass(slots=True)
class DummyLoader:
    last_pair: OpusMtPairKey | None = None

    def __call__(self, pair: OpusMtPairKey, model_dir: Path) -> OpusMtPair:
        self.last_pair = pair
        return OpusMtPair(
            source_sp=DummySentencePiece(encoded=["tok"], decoded="result"),
            target_sp=DummySentencePiece(encoded=["tok"], decoded="result"),
            translator=DummyTranslator(),
        )


def test_opus_mt_provider_translates_and_uses_pair_key() -> None:
    loader = DummyLoader()
    provider = OpusMtProvider(model_dir=Path("/tmp"), loader=loader, num_hypotheses=1)

    result = provider.translate("hello", "en", "ru")

    assert result == "result"
    assert loader.last_pair is OpusMtPairKey.EN_RU


def test_opus_mt_provider_returns_none_for_unsupported_language() -> None:
    loader = DummyLoader()
    provider = OpusMtProvider(model_dir=Path("/tmp"), loader=loader)

    result = provider.translate("hello", "de", "ru")

    assert result is None
    assert loader.last_pair is None


def test_opus_mt_provider_returns_none_for_empty_text() -> None:
    loader = DummyLoader()
    provider = OpusMtProvider(model_dir=Path("/tmp"), loader=loader)

    result = provider.translate("   ", "en", "ru")

    assert result is None
    assert loader.last_pair is None
