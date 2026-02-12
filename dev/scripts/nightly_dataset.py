from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

QueryKind = Literal["word", "phrase", "sentence"]


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    text: str
    kind: QueryKind


_GOLDEN_QUERIES: tuple[GoldenQuery, ...] = (
    GoldenQuery("a", "word"),
    GoldenQuery("i", "word"),
    GoldenQuery("run", "word"),
    GoldenQuery("set", "word"),
    GoldenQuery("state", "word"),
    GoldenQuery("mother", "word"),
    GoldenQuery("death", "word"),
    GoldenQuery("charge", "word"),
    GoldenQuery("record", "word"),
    GoldenQuery("lead", "word"),
    GoldenQuery("light", "word"),
    GoldenQuery("cold", "word"),
    GoldenQuery("bank", "word"),
    GoldenQuery("point", "word"),
    GoldenQuery("file", "word"),
    GoldenQuery("plain", "word"),
    GoldenQuery("fine", "word"),
    GoldenQuery("clear", "word"),
    GoldenQuery("stable", "word"),
    GoldenQuery("rapid", "word"),
    GoldenQuery("look up", "phrase"),
    GoldenQuery("make up", "phrase"),
    GoldenQuery("set up", "phrase"),
    GoldenQuery("break down", "phrase"),
    GoldenQuery("carry on", "phrase"),
    GoldenQuery("turn off", "phrase"),
    GoldenQuery("cold turkey", "phrase"),
    GoldenQuery("in charge", "phrase"),
    GoldenQuery("point out", "phrase"),
    GoldenQuery("work out", "phrase"),
    GoldenQuery("line up", "phrase"),
    GoldenQuery("back up", "phrase"),
    GoldenQuery("take over", "phrase"),
    GoldenQuery("check in", "phrase"),
    GoldenQuery("check out", "phrase"),
    GoldenQuery("state-of-the-art", "phrase"),
    GoldenQuery("high quality", "phrase"),
    GoldenQuery("real time", "phrase"),
    GoldenQuery("keep going", "phrase"),
    GoldenQuery("hold on", "phrase"),
    GoldenQuery("I will look it up later.", "sentence"),
    GoldenQuery("The plan was surprisingly effective.", "sentence"),
    GoldenQuery("Please keep the window open.", "sentence"),
    GoldenQuery("This service should stay responsive.", "sentence"),
    GoldenQuery("The cache keeps only normalized results.", "sentence"),
    GoldenQuery("We need stable output under burst load.", "sentence"),
    GoldenQuery("The translation quality is getting better.", "sentence"),
    GoldenQuery("I fixed the bug and pushed the commit.", "sentence"),
    GoldenQuery("The network request timed out again.", "sentence"),
    GoldenQuery("This phrase has multiple meanings in context.", "sentence"),
    GoldenQuery("He turned off the lights before leaving.", "sentence"),
    GoldenQuery("She made up the story on the spot.", "sentence"),
    GoldenQuery("They carried on despite the issue.", "sentence"),
    GoldenQuery("Please check in at the front desk.", "sentence"),
    GoldenQuery("The backend remained active all night.", "sentence"),
    GoldenQuery("The result cache should not expire entries.", "sentence"),
    GoldenQuery("History must keep only the latest hundred items.", "sentence"),
    GoldenQuery("A quick retry should not block the user interface.", "sentence"),
    GoldenQuery("The translation must stay accurate and fast.", "sentence"),
    GoldenQuery("System memory usage should stay within limits.", "sentence"),
)


def golden_queries() -> list[GoldenQuery]:
    return list(_GOLDEN_QUERIES)

