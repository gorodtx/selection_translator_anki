from __future__ import annotations

from dataclasses import dataclass

from translate_logic.models import Example, TranslationResult

_VISIBLE_EXAMPLE_LIMIT = 3


def _example_key(example: Example) -> str:
    return example.en.strip().casefold()


def _dedupe_examples(examples: tuple[Example, ...] | list[Example]) -> tuple[Example, ...]:
    deduped: list[Example] = []
    seen: set[str] = set()
    for example in examples:
        key = _example_key(example)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(Example(en=example.en.strip()))
    return tuple(deduped)


def visible_examples_from_result(result: TranslationResult) -> tuple[Example, ...]:
    return _dedupe_examples(list(result.examples)[:_VISIBLE_EXAMPLE_LIMIT])


@dataclass(frozen=True, slots=True)
class EntryExamplesState:
    lookup_text: str
    visible_examples: tuple[Example, ...]
    collected_examples: tuple[Example, ...]
    exhausted: bool

    @classmethod
    def from_result(
        cls,
        *,
        lookup_text: str,
        result: TranslationResult,
    ) -> "EntryExamplesState":
        visible = visible_examples_from_result(result)
        return cls(
            lookup_text=lookup_text.strip(),
            visible_examples=visible,
            collected_examples=visible,
            exhausted=False,
        )


@dataclass(frozen=True, slots=True)
class ExampleRefreshOutcome:
    state: EntryExamplesState
    changed: bool


def rotate_examples(
    *,
    state: EntryExamplesState,
    candidates: tuple[Example, ...] | list[Example],
) -> ExampleRefreshOutcome:
    deduped_candidates = _dedupe_examples(candidates)
    collected_keys = {_example_key(example) for example in state.collected_examples}
    unseen = [example for example in deduped_candidates if _example_key(example) not in collected_keys]
    if not unseen:
        return ExampleRefreshOutcome(
            state=EntryExamplesState(
                lookup_text=state.lookup_text,
                visible_examples=state.visible_examples,
                collected_examples=state.collected_examples,
                exhausted=True,
            ),
            changed=False,
        )
    next_visible = tuple(unseen[:_VISIBLE_EXAMPLE_LIMIT])
    next_collected = _dedupe_examples([*state.collected_examples, *next_visible])
    return ExampleRefreshOutcome(
        state=EntryExamplesState(
            lookup_text=state.lookup_text,
            visible_examples=next_visible,
            collected_examples=next_collected,
            exhausted=len(unseen) <= len(next_visible),
        ),
        changed=next_visible != state.visible_examples,
    )
