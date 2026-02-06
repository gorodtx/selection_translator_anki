from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from translate_logic.translation import clean_translations


class OpusLanguage(Enum):
    EN = "en"
    RU = "ru"


def default_opus_mt_model_dir() -> Path:
    """Return the default model directory.

    Single source of truth: repository directory `offline_assets/`.

    This directory is expected to exist after downloading the offline assets from
    GitHub Releases (see README). It contains the converted CTranslate2 models.
    """
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "offline_assets"


class OpusMtPairKey(Enum):
    EN_RU = "en-ru"

    @classmethod
    def from_languages(cls, source: str, target: str) -> OpusMtPairKey | None:
        if source == OpusLanguage.EN.value and target == OpusLanguage.RU.value:
            return cls.EN_RU
        return None


class SentencePiece(Protocol):
    def encode(self, text: str, out_type: type[str]) -> list[str]: ...

    def decode(self, pieces: Sequence[str]) -> str: ...


class Ct2TranslationResult(Protocol):
    hypotheses: Sequence[Sequence[str]]


class Ct2Translator(Protocol):
    def translate_batch(
        self,
        source: Sequence[Sequence[str]],
        *,
        beam_size: int,
        num_hypotheses: int,
        max_decoding_length: int,
        return_scores: bool,
    ) -> list[Ct2TranslationResult]: ...


@dataclass(frozen=True, slots=True)
class OpusMtPair:
    source_sp: SentencePiece
    target_sp: SentencePiece
    translator: Ct2Translator


OpusMtPairLoader = Callable[[OpusMtPairKey, Path], OpusMtPair]


def _default_pairs() -> dict[OpusMtPairKey, OpusMtPair]:
    return {}


@dataclass(slots=True)
class OpusMtProvider:
    """OPUS-MT translation provider using CTranslate2 (no PyTorch at runtime).

    Expected on-disk layout (default, repository checkout):
      offline_assets/ct2/opus_mt/<pair_key>/

    Example:
      offline_assets/ct2/opus_mt/en-ru/
        model.bin
        shared_vocabulary.json
        source.spm
        target.spm
    """

    model_dir: Path
    loader: OpusMtPairLoader = field(default_factory=lambda: _load_pair)
    beam_size: int = 4
    num_hypotheses: int = 3
    max_decoding_length: int = 24
    _pairs: dict[OpusMtPairKey, OpusMtPair] = field(default_factory=_default_pairs)

    def translate(self, text: str, source_lang: str, target_lang: str) -> str | None:
        variants = self.translate_variants(text, source_lang, target_lang, limit=1)
        if not variants:
            return None
        return variants[0]

    def translate_variants(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        *,
        limit: int | None = None,
    ) -> tuple[str, ...]:
        normalized = text.strip()
        if not normalized:
            return ()
        pair_key = OpusMtPairKey.from_languages(source_lang, target_lang)
        if pair_key is None:
            return ()

        pair = self._pairs.get(pair_key)
        if pair is None:
            try:
                pair = self.loader(pair_key, self.model_dir)
            except FileNotFoundError:
                return ()
            self._pairs[pair_key] = pair

        source_tokens = pair.source_sp.encode(normalized, out_type=str)
        # CTranslate2 expects a batch of token lists.
        results = pair.translator.translate_batch(
            [source_tokens],
            beam_size=self.beam_size,
            num_hypotheses=limit or self.num_hypotheses,
            max_decoding_length=self.max_decoding_length,
            return_scores=False,
        )
        if not results:
            return ()
        hypotheses = list(results[0].hypotheses)
        decoded = [_decode_hypothesis(pair.target_sp, hyp) for hyp in hypotheses]
        cleaned = clean_translations(decoded)
        filtered = [item for item in cleaned if _is_reasonable_variant(item)]
        effective_limit = limit or self.num_hypotheses
        return tuple(filtered[:effective_limit])


def _decode_hypothesis(sp: SentencePiece, hyp: Sequence[str]) -> str:
    value = sp.decode(hyp)
    return value.strip()


def _pair_dir(base: Path, pair: OpusMtPairKey) -> Path:
    return base / "ct2" / "opus_mt" / pair.value


def _load_pair(pair: OpusMtPairKey, model_dir: Path) -> OpusMtPair:
    import ctranslate2
    import sentencepiece as spm

    pair_dir = _pair_dir(model_dir, pair)
    source_spm = pair_dir / "source.spm"
    target_spm = pair_dir / "target.spm"
    if not source_spm.exists() or not target_spm.exists():
        msg = (
            "OPUS-MT model files are missing. Expected sentencepiece files at: "
            f"{source_spm} and {target_spm}. "
            "Download offline assets first: "
            "`uv run python scripts/download_language_bases.py`."
        )
        raise FileNotFoundError(msg)

    source_sp = spm.SentencePieceProcessor()
    source_sp.Load(str(source_spm))
    target_sp = spm.SentencePieceProcessor()
    target_sp.Load(str(target_spm))
    translator = ctranslate2.Translator(
        str(pair_dir),
        device="cpu",
        compute_type="int8",
    )
    return OpusMtPair(source_sp=source_sp, target_sp=target_sp, translator=translator)


def _is_reasonable_variant(variant: str) -> bool:
    if not variant:
        return False
    # For word/short phrase lookup we expect compact outputs.
    if len(variant) > 80:
        return False
    return True
