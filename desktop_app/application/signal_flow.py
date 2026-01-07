from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from signal import Signals
from typing import Protocol


class SignalApi(Protocol):
    @property
    def SIGUSR1(self) -> Signals | int: ...

    @property
    def SIGUSR2(self) -> Signals | int: ...

    @property
    def SIGALRM(self) -> Signals | int: ...

    @property
    def SIGINT(self) -> Signals | int: ...

    def signal(self, signum: int, handler: Callable[..., object]) -> object: ...


@dataclass(slots=True)
class SignalFlow:
    signal: SignalApi

    def install(
        self,
        on_translate: Callable[[], None],
        on_settings: Callable[[], None],
        on_history: Callable[[], None],
        on_retry: Callable[[], None],
    ) -> None:
        if not hasattr(self.signal, "SIGUSR1"):
            return
        try:
            self.signal.signal(self.signal.SIGUSR1, lambda *_: on_translate())
            self.signal.signal(self.signal.SIGUSR2, lambda *_: on_settings())
            self.signal.signal(self.signal.SIGALRM, lambda *_: on_history())
            self.signal.signal(
                getattr(self.signal, "SIGWINCH", self.signal.SIGINT),
                lambda *_: on_retry(),
            )
        except OSError:
            return


def consume_activation_action() -> str | None:
    raw = os.environ.pop("TRANSLATOR_ACTION", "").strip().casefold()
    if raw in {"settings", "translate", "history", "retry"}:
        return raw
    return None


def parse_action_args(args: list[str]) -> str | None:
    for arg in args[1:]:
        value = arg.strip().casefold()
        if value in {"--translate", "translate"}:
            return "translate"
        if value in {"--settings", "settings"}:
            return "settings"
        if value in {"--history", "history"}:
            return "history"
        if value in {"--retry", "retry"}:
            return "retry"
    return None
