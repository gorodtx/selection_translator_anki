from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass

from desktop_app.application.examples_state import ExampleRefreshOutcome, rotate_examples
from desktop_app.application.history import HistoryItem
from desktop_app.application.use_cases.translation_executor import TranslationExecutor
from translate_logic.models import Example

_EXAMPLE_REFRESH_POOL_LIMIT = 24


@dataclass(frozen=True, slots=True)
class ExampleRefreshResult:
    item: HistoryItem
    changed: bool


@dataclass(slots=True)
class ExampleRefreshUseCase:
    translation_executor: TranslationExecutor
    refresh_pool_limit: int = _EXAMPLE_REFRESH_POOL_LIMIT

    def refresh_entry(self, entry: HistoryItem) -> Future[ExampleRefreshResult]:
        completion: Future[ExampleRefreshResult] = Future()
        lookup_text = entry.examples_state.lookup_text.strip() or entry.lookup_text.strip()
        if not lookup_text:
            completion.set_result(ExampleRefreshResult(item=entry, changed=False))
            return completion
        future = self.translation_executor.refresh_examples(
            lookup_text,
            limit=self.refresh_pool_limit,
        )

        def _on_done(done: Future[tuple[Example, ...]]) -> None:
            if completion.cancelled() or completion.done():
                return
            if done.cancelled():
                completion.cancel()
                return
            try:
                candidates = done.result()
            except Exception:
                completion.set_result(ExampleRefreshResult(item=entry, changed=False))
                return
            rotated: ExampleRefreshOutcome = rotate_examples(
                state=entry.examples_state,
                candidates=candidates,
            )
            updated_item = self.translation_executor.update_entry_examples(
                entry.entry_id,
                rotated.state,
            )
            completion.set_result(
                ExampleRefreshResult(
                    item=updated_item or HistoryItem(
                        entry_id=entry.entry_id,
                        text=entry.text,
                        lookup_text=lookup_text,
                        result=entry.result,
                        examples_state=rotated.state,
                    ),
                    changed=rotated.changed,
                )
            )

        future.add_done_callback(_on_done)
        return completion
