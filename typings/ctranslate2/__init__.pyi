from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Protocol

class TranslationResult(Protocol):
    hypotheses: Sequence[Sequence[str]]

class Translator:
    def __init__(
        self,
        model_path: str,
        device: str = ...,
        *,
        device_index: int | list[int] = ...,
        compute_type: str | dict[str, str] = ...,
        inter_threads: int = ...,
        intra_threads: int = ...,
        max_queued_batches: int = ...,
        flash_attention: bool = ...,
        tensor_parallel: bool = ...,
        files: object = ...,
    ) -> None: ...
    def translate_batch(
        self,
        source: Sequence[Sequence[str]],
        target_prefix: object | None = ...,
        *,
        beam_size: int = ...,
        num_hypotheses: int = ...,
        length_penalty: float = ...,
        repetition_penalty: float = ...,
        no_repeat_ngram_size: int = ...,
        end_token: object | None = ...,
        max_decoding_length: int = ...,
        return_scores: bool = ...,
    ) -> list[TranslationResult]: ...

__all__: Final[list[str]]
