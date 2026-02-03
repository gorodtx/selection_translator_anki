from __future__ import annotations

from collections.abc import Sequence

class AutoTokenizer:
    @classmethod
    def from_pretrained(
        cls,
        pretrained_model_name_or_path: str,
        **kwargs: object,
    ) -> AutoTokenizer: ...
    def __call__(
        self,
        text: str | Sequence[str],
        return_tensors: str | None = ...,
        **kwargs: object,
    ) -> dict[str, object]: ...
    def decode(
        self,
        token_ids: Sequence[int] | object,
        skip_special_tokens: bool = ...,
    ) -> str: ...

class AutoModelForSeq2SeqLM:
    @classmethod
    def from_pretrained(
        cls,
        pretrained_model_name_or_path: str,
        **kwargs: object,
    ) -> AutoModelForSeq2SeqLM: ...
    def generate(self, **kwargs: object) -> Sequence[Sequence[int]]: ...
