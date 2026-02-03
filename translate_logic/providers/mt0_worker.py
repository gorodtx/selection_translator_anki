from __future__ import annotations

from typing import Final

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

_MODEL = None
_TOKENIZER = None
_DEFAULT_MODEL: Final[str] = "google/mt0-small"


def generate_mt0_prompt(
    prompt: str,
    model_name: str | None = None,
    cache_dir: str | None = None,
    max_new_tokens: int = 128,
    temperature: float = 0.3,
) -> str:
    global _MODEL, _TOKENIZER
    model_id = model_name or _DEFAULT_MODEL
    if _TOKENIZER is None or _MODEL is None:
        _TOKENIZER = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
        _MODEL = AutoModelForSeq2SeqLM.from_pretrained(model_id, cache_dir=cache_dir)
    encoded = _TOKENIZER(prompt, return_tensors="pt")
    outputs = _MODEL.generate(
        **encoded,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
    )
    if not outputs:
        return ""
    return _TOKENIZER.decode(outputs[0], skip_special_tokens=True)
