from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from desktop_app.application.anki_upsert import AnkiUpsertDecision, AnkiUpsertPreview
from desktop_app import gtk_types
from desktop_app.application.view_state import (
    TranslationPresenter,
    TranslationViewState,
)
from desktop_app.notifications import Notification
from translate_logic.models import TranslationResult


class TranslationWindowProtocol(Protocol):
    @property
    def window(self) -> gtk_types.Gtk.ApplicationWindow: ...

    def present(self) -> None: ...

    def hide(self) -> None: ...

    def apply_state(self, state: TranslationViewState) -> None: ...

    def show_banner(self, notification: Notification) -> None: ...

    def clear_banner(self) -> None: ...

    def show_anki_upsert(
        self,
        preview: AnkiUpsertPreview,
        on_apply: Callable[[AnkiUpsertDecision], None],
        on_cancel: Callable[[], None],
    ) -> None: ...

    def hide_anki_upsert(self) -> None: ...


def _build_window(
    *,
    app: gtk_types.Gtk.Application,
    on_close: Callable[[], None],
    on_copy_all: Callable[[], None],
    on_add: Callable[[], None],
) -> TranslationWindowProtocol:
    from desktop_app.ui.translation_window import TranslationWindow

    return TranslationWindow(
        app=app,
        on_close=on_close,
        on_copy_all=on_copy_all,
        on_add=on_add,
    )


class TranslationViewCoordinator:
    def __init__(
        self,
        *,
        app: gtk_types.Gtk.Application,
        on_close: Callable[[], None],
        on_copy_all: Callable[[], None],
        on_add: Callable[[], None],
    ) -> None:
        self._window = _build_window(
            app=app,
            on_close=on_close,
            on_copy_all=on_copy_all,
            on_add=on_add,
        )
        self._presenter = TranslationPresenter()
        self._visible = False
        self._last_applied_state: TranslationViewState | None = None
        self._apply_state(self._presenter.state)

    @property
    def state(self) -> TranslationViewState:
        return self._presenter.state

    def begin(self, original: str) -> None:
        self._window.clear_banner()
        self._apply_state(self._presenter.begin(original))

    def apply_partial(self, result: TranslationResult) -> None:
        self._apply_state(self._presenter.apply_partial(result))

    def apply_final(self, result: TranslationResult) -> None:
        self._apply_state(self._presenter.apply_final(result))

    def mark_error(self) -> None:
        self._apply_state(self._presenter.mark_error())

    def set_anki_available(self, available: bool) -> None:
        self._apply_state(self._presenter.set_anki_available(available))

    def reset_original(self, original: str) -> None:
        self._apply_state(self._presenter.reset_original(original))

    def present(self, *, should_present: bool) -> bool:
        if not should_present:
            return False
        self._window.present()
        self._visible = True
        return True

    def hide(self) -> None:
        self._window.hide()
        self._visible = False

    def is_visible(self) -> bool:
        return self._visible

    def window(self) -> gtk_types.Gtk.ApplicationWindow | None:
        if not self._visible:
            return None
        return self._window.window

    def notify(self, notification: Notification) -> None:
        self._window.show_banner(notification)

    def show_anki_upsert(
        self,
        preview: AnkiUpsertPreview,
        on_apply: Callable[[AnkiUpsertDecision], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._window.show_anki_upsert(
            preview=preview,
            on_apply=on_apply,
            on_cancel=on_cancel,
        )

    def hide_anki_upsert(self) -> None:
        self._window.hide_anki_upsert()

    def _apply_state(self, state: TranslationViewState) -> None:
        if self._last_applied_state == state:
            return
        self._window.apply_state(state)
        self._last_applied_state = state
