from __future__ import annotations

from desktop_app.application.use_cases.anki_flow import AnkiFlow
from desktop_app.application.use_cases.anki_upsert_flow import AnkiUpsertCoordinator
from desktop_app.presentation.controllers.settings_controller import glib_dispatch


class AnkiController(AnkiUpsertCoordinator):
    def __init__(self, *, anki_flow: AnkiFlow) -> None:
        super().__init__(anki_flow=anki_flow, dispatch=glib_dispatch)
