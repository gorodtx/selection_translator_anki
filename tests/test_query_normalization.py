from __future__ import annotations

from desktop_app.application.query import normalize_query_text


def test_normalize_query_text_preserves_letters() -> None:
    assert normalize_query_text("model_class") == "model class"


def test_normalize_query_text_preserves_apostrophes_and_hyphens() -> None:
    assert normalize_query_text("don't-stop") == "don't-stop"


def test_normalize_query_text_strips_noise() -> None:
    assert normalize_query_text("  !!! ") == ""
