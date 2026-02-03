from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def _default_pairs() -> dict["OpusMtPairKey", "OpusMtPair"]:
    return {}


class OpusLanguage(Enum):
    EN = "en"
    RU = "ru"


class OpusMtModel(Enum):
    EN_RU = "Helsinki-NLP/opus-mt-en-ru"
    RU_EN = "Helsinki-NLP/opus-mt-ru-en"


class OpusMtPairKey(Enum):
    EN_RU = "en-ru"
    RU_EN = "ru-en"

    @classmethod
    def from_languages(cls, source: str, target: str) -> "OpusMtPairKey" | None:
        if source == OpusLanguage.EN.value and target == OpusLanguage.RU.value:
            return cls.EN_RU
        if source == OpusLanguage.RU.value and target == OpusLanguage.EN.value:
            return cls.RU_EN
        return None


class OpusTokenizer(Protocol):
    def __call__(
        self, text: str, return_tensors: str, **kwargs: object
    ) -> dict[str, object]: ...

    def decode(
        self,
        token_ids: Sequence[int] | object,
        skip_special_tokens: bool = True,
    ) -> str: ...


class OpusModel(Protocol):
    def generate(self, **kwargs: object) -> Sequence[Sequence[int]]: ...


@dataclass(frozen=True, slots=True)
class OpusMtPair:
    tokenizer: OpusTokenizer
    model: OpusModel


OpusMtPairLoader = Callable[[OpusMtModel, Path | None], OpusMtPair]


@dataclass(slots=True)
class OpusMtProvider:
    model_dir: Path | None = None
    loader: OpusMtPairLoader = field(default_factory=lambda: _load_pair)
    _pairs: dict[OpusMtPairKey, OpusMtPair] = field(default_factory=_default_pairs)

    def translate(self, text: str, source_lang: str, target_lang: str) -> str | None:
        normalized = text.strip()
        if not normalized:
            return None
        pair_key = OpusMtPairKey.from_languages(source_lang, target_lang)
        if pair_key is None:
            return None
        pair = self._pairs.get(pair_key)
        if pair is None:
            model_name = _pair_model(pair_key)
            pair = self.loader(model_name, self.model_dir)
            self._pairs[pair_key] = pair
        encoded = pair.tokenizer(normalized, return_tensors="pt")
        outputs = pair.model.generate(**encoded)
        if not outputs:
            return None
        decoded = pair.tokenizer.decode(outputs[0], skip_special_tokens=True)
        normalized_output = decoded.strip()
        return normalized_output or None


def _pair_model(pair: OpusMtPairKey) -> OpusMtModel:
    if pair is OpusMtPairKey.EN_RU:
        return OpusMtModel.EN_RU
    return OpusMtModel.RU_EN


def _load_pair(model: OpusMtModel, cache_dir: Path | None) -> OpusMtPair:
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model.value, cache_dir=cache_dir)
    model_instance = AutoModelForSeq2SeqLM.from_pretrained(
        model.value,
        cache_dir=cache_dir,
    )
    return OpusMtPair(tokenizer=tokenizer, model=model_instance)
