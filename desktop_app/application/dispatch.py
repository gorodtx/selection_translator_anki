from __future__ import annotations

from collections.abc import Callable

# Marshals a callable onto the UI/main loop thread. GTK passes a GLib.idle_add
# wrapper, the macOS daemon passes ``loop.call_soon_threadsafe``.
type Dispatch = Callable[[Callable[[], None]], None]


def call_inline(callback: Callable[[], None]) -> None:
    callback()
