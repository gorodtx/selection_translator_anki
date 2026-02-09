from __future__ import annotations

from translate_logic.translation import (
    combine_translation_variants,
    select_translation_candidates,
)


def test_combine_translation_variants_limits_and_dedupes() -> None:
    primary = ["alpha", "beta", "gamma"]
    secondary = ["beta", "delta", "epsilon"]
    combined = combine_translation_variants(primary, secondary)
    assert combined == "alpha; beta; gamma; delta"


def test_select_translation_candidates_prefers_non_meta() -> None:
    translations = ["от гл.", "перевод"]
    candidates = select_translation_candidates(translations)
    assert candidates == ["перевод"]
