"""End-to-end Anki flow against a real HTTP AnkiConnect stand-in.

Anki is not installable on the build machine, so this is the only automated
proof that the add / update / merge / image path works over the wire rather
than only against hand-written fakes of our own ports.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
import json
from pathlib import Path
import struct
import subprocess
import sys
import urllib.request
import zlib

import pytest

from desktop_app.application.use_cases.anki_flow import AnkiFlow, AnkiOutcome
from desktop_app.application.use_cases.anki_upsert import (
    AnkiFieldAction,
    AnkiImageAction,
    AnkiUpsertDecision,
)
from desktop_app.config import AnkiConfig, AnkiFieldMap
from desktop_app.infrastructure.anki import DEFAULT_TIMEOUT_SECONDS, AnkiListResult
from desktop_app.infrastructure.anki.service import AnkiService
from desktop_app.infrastructure.anki.templates import (
    DEFAULT_BACK_TEMPLATE,
    DEFAULT_FRONT_TEMPLATE,
    DEFAULT_MODEL_CSS,
    DEFAULT_MODEL_FIELDS,
    DEFAULT_MODEL_NAME,
)
from desktop_app.infrastructure.services.runtime import AsyncRuntime
from tests.fakes.anki_connect import FakeAnkiConnect, FakeAnkiState, Note
from translate_logic.models import Example, FieldValue, TranslationResult

FIELDS = AnkiFieldMap(
    word="word",
    translation="translation",
    example_en="example_en",
    definitions_en="definitions_en",
    image="image",
)


def _png(path: Path) -> Path:
    """A one-pixel PNG: the importer decodes the image before uploading it."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )
    return path


def _result() -> TranslationResult:
    return TranslationResult(
        translation_ru=FieldValue.present("берег; банка"),
        definitions_en=("the land alongside a river",),
        examples=(Example("The bank is closed."), Example("We sat on the bank.")),
    )


@pytest.fixture
def anki() -> object:
    runtime = AsyncRuntime()
    runtime.start()
    with FakeAnkiConnect(FakeAnkiState()) as server:
        service = AnkiService(
            runtime, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, base_url=server.url
        )
        try:
            yield server, AnkiFlow(service=service)
        finally:
            asyncio.run_coroutine_threadsafe(service.close(), runtime.loop).result(5)
            runtime.stop()


def _wait[T](future: Future[T]) -> T:
    return future.result(timeout=10)


def test_model_is_created_over_the_wire(anki: tuple[FakeAnkiConnect, AnkiFlow]) -> None:
    server, flow = anki

    result = _wait(
        flow.create_model(
            DEFAULT_MODEL_NAME,
            DEFAULT_MODEL_FIELDS,
            DEFAULT_FRONT_TEMPLATE,
            DEFAULT_BACK_TEMPLATE,
            DEFAULT_MODEL_CSS,
        )
    )

    assert result.error is None and result.success
    assert server.state.models[DEFAULT_MODEL_NAME] == DEFAULT_MODEL_FIELDS
    assert _wait(flow.model_names()).items == [DEFAULT_MODEL_NAME]
    assert _wait(flow.refresh_decks()).items == ["Default", "English"]


def test_add_then_duplicate_then_merge_and_image(
    anki: tuple[FakeAnkiConnect, AnkiFlow], tmp_path: Path
) -> None:
    server, flow = anki
    server.state.models[DEFAULT_MODEL_NAME] = list(DEFAULT_MODEL_FIELDS)
    config = AnkiConfig(deck="English", model=DEFAULT_MODEL_NAME, fields=FIELDS)

    # 1. A fresh note is created with the mapped fields.
    outcomes: list[AnkiOutcome] = []
    _wait(
        flow.add_note(config, "bank", _result(), lambda r: outcomes.append(r.outcome))
    )
    assert outcomes == [AnkiOutcome.SUCCESS]
    assert [note.deck for note in server.state.notes.values()] == ["English"]
    stored = next(iter(server.state.notes.values())).fields
    assert stored["word"] == "bank"
    assert "берег" in stored["translation"]
    assert 'The <mark class="hl">bank</mark> is closed.' in stored["example_en"]
    assert "the land alongside a river" in stored["definitions_en"]

    # 2. Preparing again finds the existing note instead of blindly adding.
    preview = _wait(flow.prepare_upsert(config, "bank", _result())).preview
    assert preview is not None
    assert [match.word for match in preview.matches] == ["bank"]
    note_id = preview.matches[0].note_id

    # 3. Merging appends only what is missing, and the image is uploaded.
    image = _png(tmp_path / "shot.png")
    decision = AnkiUpsertDecision(
        create_new=False,
        target_note_ids=(note_id,),
        translation_action=AnkiFieldAction.MERGE_UNIQUE_SELECTED,
        definitions_action=AnkiFieldAction.KEEP_EXISTING,
        examples_action=AnkiFieldAction.MERGE_UNIQUE_SELECTED,
        image_action=AnkiImageAction.REPLACE_WITH_SELECTED,
        selected_translations=("отмель",),
        selected_definitions_en=(),
        selected_examples_en=("A new sentence about the bank.",),
        image_path=str(image),
    )

    applied = _wait(
        flow.apply_upsert(
            config=config, original_text="bank", preview=preview, decision=decision
        )
    )

    assert applied.outcome in {AnkiOutcome.UPDATED, AnkiOutcome.SUCCESS}, (
        applied.message
    )
    merged = server.state.notes[note_id].fields
    assert "отмель" in merged["translation"]
    assert "берег" in merged["translation"], "merge must not drop what was there"
    # Examples reach Anki with the query term highlighted, and the merge keeps
    # what was already on the note.
    assert (
        'A new sentence about the <mark class="hl">bank</mark>.' in merged["example_en"]
    )
    assert 'The <mark class="hl">bank</mark> is closed.' in merged["example_en"]
    assert server.state.media, "the image was never uploaded"
    filename = next(iter(server.state.media))
    assert filename.endswith(".png")
    assert f'<img src="{filename}"' in merged["image"]
    assert 'alt="bank"' in merged["image"], "the alt text carries the headword"
    # The bytes the app uploaded are the bytes of the file it was given.
    assert server.state.media[filename] == image.read_bytes()

    actions = [action for action, _ in server.state.calls]
    assert "storeMediaFile" in actions
    assert "updateNoteFields" in actions


def test_unavailable_backend_is_reported_not_raised(tmp_path: Path) -> None:
    runtime = AsyncRuntime()
    runtime.start()
    # Nothing is listening on this port.
    service = AnkiService(runtime, timeout_seconds=1.0, base_url="http://127.0.0.1:1")
    flow = AnkiFlow(service=service)
    try:
        decks = _wait(flow.refresh_decks())
        assert decks.error is not None and decks.items == []
        preview = _wait(
            flow.prepare_upsert(
                AnkiConfig(deck="English", model=DEFAULT_MODEL_NAME, fields=FIELDS),
                "bank",
                _result(),
            )
        )
        assert preview.error is not None or preview.preview is not None
    finally:
        asyncio.run_coroutine_threadsafe(service.close(), runtime.loop).result(5)
        runtime.stop()


def test_action_failure_surfaces_as_an_error(
    anki: tuple[FakeAnkiConnect, AnkiFlow],
) -> None:
    server, flow = anki
    server.state.fail_action = "modelNames"

    result = _wait(flow.model_names())

    assert result.error is not None
    assert result.items == []


def test_empty_lists_are_answers_not_protocol_errors(
    anki: tuple[FakeAnkiConnect, AnkiFlow],
) -> None:
    """A profile with no models, and a word that matches nothing, are normal.

    Both used to come back as "Invalid AnkiConnect response", because the guard
    that catches a malformed payload also fired on a legitimate empty list. The
    second case is the common one: every word added for the first time makes
    `findNotes` return `[]`.
    """
    server, flow = anki
    assert server.state.models == {}

    models = _wait(flow.model_names())
    assert models == AnkiListResult(items=[], error=None)

    server.state.models[DEFAULT_MODEL_NAME] = list(DEFAULT_MODEL_FIELDS)
    config = AnkiConfig(deck="English", model=DEFAULT_MODEL_NAME, fields=FIELDS)

    preview = _wait(flow.prepare_upsert(config, "unseen", _result()))

    assert preview.error is None
    assert preview.preview is not None
    assert preview.preview.matches == ()
    assert preview.preview.available_fields == tuple(DEFAULT_MODEL_FIELDS)


def test_the_stand_in_can_be_served_standalone() -> None:
    """`python -m tests.fakes.anki_connect` is how a machine without Anki

    drives the real flow: it prints the URL to feed to `ANKI_CONNECT_URL`.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fakes.anki_connect"],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line.startswith("ANKI_CONNECT_URL=http://127.0.0.1:")
        url = line.split("=", 1)[1]
        request = urllib.request.Request(
            url,
            data=json.dumps({"action": "modelNames", "version": 6}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        # A model is pre-created so the flow has something to add notes to.
        assert payload["error"] is None
        assert payload["result"] == [DEFAULT_MODEL_NAME]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_only_notes_in_the_apps_own_field_shape_are_matched(
    anki: tuple[FakeAnkiConnect, AnkiFlow],
) -> None:
    """Matching keys on the configured field name, so a hand-made note is missed.

    That is the right call — the app cannot know that a field called `Word`
    holds the headword — but it has a consequence worth stating: pointed at an
    existing hand-made deck, the app adds new notes instead of updating the
    ones already there.
    """
    server, flow = anki
    server.state.models[DEFAULT_MODEL_NAME] = list(DEFAULT_MODEL_FIELDS)
    server.state.notes[999] = Note(
        999, DEFAULT_MODEL_NAME, "English", {"Word": "bank", "Translation": "берег"}
    )
    server.state.notes[1000] = Note(
        1000, DEFAULT_MODEL_NAME, "English", {"word": "bank", "translation": "старый"}
    )
    config = AnkiConfig(deck="English", model=DEFAULT_MODEL_NAME, fields=FIELDS)

    preview = _wait(flow.prepare_upsert(config, "bank", _result())).preview

    assert preview is not None
    assert [match.note_id for match in preview.matches] == [1000]
    # Both notes were fetched, but the field list dedupes case-insensitively,
    # so the sheet offers `word` once instead of `word` and `Word` as two.
    assert preview.available_fields == tuple(DEFAULT_MODEL_FIELDS)
    assert "Word" not in preview.available_fields


def test_merge_keeps_what_was_on_the_note(
    anki: tuple[FakeAnkiConnect, AnkiFlow],
) -> None:
    server, flow = anki
    server.state.models[DEFAULT_MODEL_NAME] = list(DEFAULT_MODEL_FIELDS)
    server.state.notes[1000] = Note(
        1000,
        DEFAULT_MODEL_NAME,
        "English",
        {"word": "bank", "translation": "старый перевод"},
    )
    config = AnkiConfig(deck="English", model=DEFAULT_MODEL_NAME, fields=FIELDS)
    preview = _wait(flow.prepare_upsert(config, "bank", _result())).preview
    assert preview is not None

    applied = _wait(
        flow.apply_upsert(
            config=config,
            original_text="bank",
            preview=preview,
            decision=AnkiUpsertDecision(
                create_new=False,
                target_note_ids=(1000,),
                translation_action=AnkiFieldAction.MERGE_UNIQUE_SELECTED,
                definitions_action=AnkiFieldAction.KEEP_EXISTING,
                examples_action=AnkiFieldAction.KEEP_EXISTING,
                image_action=AnkiImageAction.KEEP_EXISTING,
                selected_translations=("берег",),
                selected_definitions_en=(),
                selected_examples_en=(),
                image_path=None,
            ),
        )
    )

    assert applied.outcome is AnkiOutcome.UPDATED, applied.message
    merged = server.state.notes[1000].fields["translation"]
    assert merged == "старый перевод; берег"
