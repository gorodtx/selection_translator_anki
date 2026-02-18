from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from desktop_app import gtk_types
from desktop_app.application.history import HistoryItem


class HistoryWindowProtocol(Protocol):
    @property
    def window(self) -> gtk_types.Gtk.ApplicationWindow: ...

    def present(self) -> None: ...

    def hide(self) -> None: ...

    def refresh(self, items: Iterable[HistoryItem]) -> None: ...


def _build_window(
    *,
    app: gtk_types.Gtk.Application,
    on_close: Callable[[], None],
    on_select: Callable[[HistoryItem], None],
) -> HistoryWindowProtocol:
    from desktop_app.presentation.ui.history_window import HistoryWindow

    return HistoryWindow(
        app=app,
        on_close=on_close,
        on_select=on_select,
    )


class HistoryViewCoordinator:
    def __init__(
        self,
        *,
        app: gtk_types.Gtk.Application,
        history_provider: Callable[[], list[HistoryItem]],
        on_select: Callable[[HistoryItem], None],
        on_present_window: Callable[[gtk_types.Gtk.ApplicationWindow], None],
    ) -> None:
        self._history_provider = history_provider
        self._on_present_window = on_present_window
        self._window = _build_window(
            app=app,
            on_close=self._on_close,
            on_select=on_select,
        )
        self._is_open = False

    @property
    def is_open(self) -> bool:
        return self._is_open

    def show(self) -> None:
        self.refresh()
        self._window.present()
        self._is_open = True
        self._on_present_window(self._window.window)

    def hide(self) -> None:
        self._window.hide()
        self._is_open = False

    def refresh(self) -> None:
        items = self._history_provider()
        self._window.refresh(items)

    def _on_close(self) -> None:
        self.hide()
