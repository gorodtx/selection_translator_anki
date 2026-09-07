"""Fetching the offline bases from inside the app."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from desktop_app.platform.macos.db_download import (
    DatabaseDownloader,
    DownloadState,
    LockError,
    Progress,
    digest_of,
    load_assets,
    resolve_lock_path,
)


def _lock(tmp_path: Path, assets: dict[str, str]) -> Path:
    path = tmp_path / "db-bundle.lock.json"
    path.write_text(
        json.dumps(
            {
                "repo": "gorodtx/selection_translator_anki",
                "tag": "db-test",
                "assets": {
                    name: {"name": name, "sha256": d} for name, d in assets.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_urls_and_digests_come_from_the_lock(tmp_path: Path) -> None:
    path = _lock(tmp_path, {"primary.sqlite3": "aa", "fallback.sqlite3": "bb"})

    assets = load_assets(path)

    assert [a.name for a in assets] == ["fallback.sqlite3", "primary.sqlite3"]
    assert assets[0].url == (
        "https://github.com/gorodtx/selection_translator_anki/releases/download/"
        "db-test/fallback.sqlite3"
    )


def test_the_real_lock_in_this_repo_parses() -> None:
    assets = load_assets(resolve_lock_path())

    assert {a.name for a in assets} == {
        "primary.sqlite3",
        "fallback.sqlite3",
        "definitions_pack.sqlite3",
    }
    assert all(len(a.sha256) == 64 for a in assets)


@pytest.mark.parametrize(
    "payload",
    ['{"repo": "r"}', "[]", '{"repo": "r", "tag": "t", "assets": {}}', "not json"],
)
def test_a_malformed_lock_is_refused_not_guessed(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "lock.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(LockError):
        load_assets(path)


def test_a_file_that_already_matches_is_not_fetched_again(tmp_path: Path) -> None:
    body = b"already here"
    digest = hashlib.sha256(body).hexdigest()
    store = tmp_path / "db"
    store.mkdir()
    (store / "primary.sqlite3").write_bytes(body)
    events: list[Progress] = []

    downloader = DatabaseDownloader(
        lock_path=_lock(tmp_path, {"primary.sqlite3": digest}),
        target_dir=store,
        emit=events.append,
    )

    async def scenario() -> tuple[str, ...]:
        pending = downloader.start()
        await downloader.wait()
        return pending

    assert asyncio.run(scenario()) == ()
    # Nothing was started, so no session was ever opened.
    assert events == []


def test_a_missing_file_is_downloaded_and_verified(tmp_path: Path) -> None:
    body = b"x" * 4096
    digest = hashlib.sha256(body).hexdigest()
    store = tmp_path / "db"
    events: list[Progress] = []
    downloader = DatabaseDownloader(
        lock_path=_lock(tmp_path, {"primary.sqlite3": digest}),
        target_dir=store,
        emit=events.append,
        session_factory=lambda: cast("object", _FakeSession({"primary.sqlite3": body})),  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        assert downloader.start() == ("primary.sqlite3",)
        await downloader.wait()

    asyncio.run(scenario())

    assert (store / "primary.sqlite3").read_bytes() == body
    assert not list(store.glob("*.part")), "the partial file was left behind"
    states = [event.state for event in events]
    assert DownloadState.DOWNLOADING in states
    assert states[-1] is DownloadState.DONE


def test_a_wrong_checksum_leaves_no_file_behind(tmp_path: Path) -> None:
    """A wrong base is worse than none: it would be read as if it were right."""
    store = tmp_path / "db"
    events: list[Progress] = []
    downloader = DatabaseDownloader(
        lock_path=_lock(tmp_path, {"primary.sqlite3": "0" * 64}),
        target_dir=store,
        emit=events.append,
        session_factory=lambda: cast(
            "object", _FakeSession({"primary.sqlite3": b"junk"})
        ),  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        downloader.start()
        await downloader.wait()

    asyncio.run(scenario())

    assert not (store / "primary.sqlite3").exists()
    assert not list(store.glob("*.part"))
    assert events[-1].state is DownloadState.FAILED
    assert events[-1].error == "checksum mismatch"


def test_an_http_error_is_reported_not_raised(tmp_path: Path) -> None:
    store = tmp_path / "db"
    events: list[Progress] = []
    downloader = DatabaseDownloader(
        lock_path=_lock(tmp_path, {"primary.sqlite3": "0" * 64}),
        target_dir=store,
        emit=events.append,
        session_factory=lambda: cast("object", _FakeSession({}, status=404)),  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        downloader.start()
        await downloader.wait()

    asyncio.run(scenario())

    assert events[-1].state is DownloadState.FAILED
    assert "404" in (events[-1].error or "")


def test_digest_of_reads_large_files_in_chunks(tmp_path: Path) -> None:
    path = tmp_path / "big"
    body = b"ab" * (5 << 20)
    path.write_bytes(body)

    assert digest_of(path) == hashlib.sha256(body).hexdigest()


def test_a_second_request_joins_the_one_in_flight(tmp_path: Path) -> None:
    body = b"y" * 2048
    digest = hashlib.sha256(body).hexdigest()
    downloader = DatabaseDownloader(
        lock_path=_lock(tmp_path, {"primary.sqlite3": digest}),
        target_dir=tmp_path / "db",
        emit=lambda progress: None,
        session_factory=lambda: cast(
            "object", _FakeSession({"primary.sqlite3": body}, delay=0.05)
        ),  # type: ignore[arg-type]
    )

    async def scenario() -> tuple[bool, bool]:
        downloader.start()
        first = downloader.is_running
        downloader.start()  # must not spawn a second task
        second = downloader.is_running
        await downloader.wait()
        return first, second

    first, second = asyncio.run(scenario())

    assert first and second
    assert not downloader.is_running


# --- a session stand-in, so no test touches the network ------------------------


class _FakeResponse:
    def __init__(self, body: bytes, status: int, delay: float) -> None:
        self._body = body
        self.status = status
        self._delay = delay

    @property
    def content_length(self) -> int:
        return len(self._body)

    @property
    def content(self) -> "_FakeResponse":
        return self

    async def iter_chunked(self, size: int):  # noqa: ANN201 - async generator
        for start in range(0, len(self._body), size):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield self._body[start : start + size]

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakeSession:
    def __init__(
        self, bodies: dict[str, bytes], status: int = 200, delay: float = 0.0
    ) -> None:
        self._bodies = bodies
        self._status = status
        self._delay = delay

    def get(self, url: str, **_: object) -> _FakeResponse:
        name = url.rsplit("/", 1)[-1]
        body = self._bodies.get(name, b"")
        return _FakeResponse(body, self._status, self._delay)

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None
