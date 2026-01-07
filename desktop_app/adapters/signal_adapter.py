from __future__ import annotations

from dataclasses import dataclass
import signal as signal_module
from typing import Callable


@dataclass(slots=True)
class SignalAdapter:
    @property
    def SIGUSR1(self) -> int:
        return int(signal_module.SIGUSR1)

    @property
    def SIGUSR2(self) -> int:
        return int(signal_module.SIGUSR2)

    @property
    def SIGALRM(self) -> int:
        return int(signal_module.SIGALRM)

    @property
    def SIGINT(self) -> int:
        return int(signal_module.SIGINT)

    def signal(self, signum: int, handler: Callable[..., object]) -> object:
        return signal_module.signal(signum, handler)
