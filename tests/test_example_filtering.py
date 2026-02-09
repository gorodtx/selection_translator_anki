from __future__ import annotations

from translate_logic.application import translate as translate_app
from translate_logic.models import Example


def test_filter_examples_requires_two_words() -> None:
    examples = [
        Example(en="Hello", ru="Привет"),
        Example(en="Hello world", ru="Привет мир"),
    ]
    assert translate_app.filter_examples(examples) == [
        Example(en="Hello world", ru="Привет мир")
    ]
