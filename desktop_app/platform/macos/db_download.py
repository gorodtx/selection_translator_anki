"""Fetch the offline bases from inside the app.

Until now only `scripts/install_macos.sh` could do this, so a user whose store
is empty — a hand-placed bundle, deleted bases, a changed
``TRANSLATOR_DB_DIR`` — could be told they were missing and nothing more. The
onboarding step needs a button, so the daemon needs a method.

The contract is the installer's: URLs and digests come from
``scripts/db-bundle.lock.json``, every file is verified before it is moved into
place, and a file that already matches its digest is not fetched again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import logging
from pathlib import Path
from typing import Final, cast

import aiohttp

_LOGGER = logging.getLogger(__name__)
_CHUNK_BYTES: Final[int] = 1 << 20
_HASH_CHUNK_BYTES: Final[int] = 8 << 20
_PROGRESS_MIN_INTERVAL_S: Final[float] = 0.25
_REQUEST_TIMEOUT_S: Final[float] = 60.0


class DownloadState(StrEnum):
    PRESENT = "present"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Progress:
    file: str
    state: DownloadState
    received: int
    total: int
    error: str | None = None


type ProgressSink = Callable[[Progress], None]


class LockError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Asset:
    name: str
    sha256: str
    url: str
    # What the release says this asset weighs. 0 means the lock predates the
    # field: callers must treat it as unknown, never as an empty file.
    size: int = 0


def resolve_lock_path() -> Path:
    """Where the lock lives differs between a checkout and a bundle.

    The build copies it to `Contents/Resources/db-bundle.lock.json`, next to
    the `app/` tree rather than under it, so a repo-relative path finds nothing
    once installed — and the download button would fail only for real users.
    """
    module_dir = Path(__file__).resolve().parent
    candidates = (
        # Bundle: .../Resources/app/desktop_app/platform/macos -> .../Resources
        module_dir.parents[3] / "db-bundle.lock.json",
        # Checkout: .../desktop_app/platform/macos -> repo root
        module_dir.parents[2] / "scripts" / "db-bundle.lock.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


def _as_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    items = cast(dict[object, object], value)
    return {str(key): item for key, item in items.items()}


def load_assets(lock_path: Path) -> tuple[Asset, ...]:
    """Read the same lock the installer reads; never guess a URL."""
    try:
        decoded: object = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockError(f"cannot read {lock_path}: {exc}") from exc
    payload = _as_object(decoded)
    if payload is None:
        raise LockError(f"{lock_path} is not an object")
    repo = payload.get("repo")
    tag = payload.get("tag")
    assets = _as_object(payload.get("assets"))
    if not isinstance(repo, str) or not isinstance(tag, str):
        raise LockError(f"{lock_path} has no repo/tag")
    if assets is None:
        raise LockError(f"{lock_path} has no assets")
    resolved: list[Asset] = []
    for name, raw_meta in assets.items():
        meta = _as_object(raw_meta)
        if meta is None:
            continue
        digest = meta.get("sha256")
        if not isinstance(digest, str):
            continue
        raw_size = meta.get("size")
        size = raw_size if isinstance(raw_size, int) and raw_size >= 0 else 0
        resolved.append(
            Asset(
                name=name,
                sha256=digest,
                url=f"https://github.com/{repo}/releases/download/{tag}/{name}",
                size=size,
            )
        )
    if not resolved:
        raise LockError(f"{lock_path} lists no usable assets")
    return tuple(sorted(resolved, key=lambda item: item.name))


def digest_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class DatabaseDownloader:
    """One download at a time; a second request joins the one in flight."""

    def __init__(
        self,
        *,
        lock_path: Path,
        target_dir: Path,
        emit: ProgressSink,
        session_factory: Callable[[], aiohttp.ClientSession] | None = None,
    ) -> None:
        self._lock_path = lock_path
        self._target_dir = target_dir
        self._emit = emit
        self._session_factory = session_factory or aiohttp.ClientSession
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> tuple[str, ...]:
        """Begin fetching whatever is missing; return the names it will touch."""
        assets = load_assets(self._lock_path)
        missing = tuple(asset.name for asset in assets if not self._is_present(asset))
        if self.is_running or not missing:
            return missing
        self._task = asyncio.create_task(self._run(assets))
        return missing

    def cancel(self) -> bool:
        if not self.is_running or self._task is None:
            return False
        self._task.cancel()
        return True

    async def wait(self) -> None:
        task = self._task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _is_present(self, asset: Asset) -> bool:
        target = self._target_dir / asset.name
        if not target.is_file():
            return False
        try:
            return digest_of(target) == asset.sha256
        except OSError:
            return False

    async def _run(self, assets: Sequence[Asset]) -> None:
        try:
            self._target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._emit(Progress("", DownloadState.FAILED, 0, 0, str(exc)))
            return
        try:
            async with self._session_factory() as session:
                for asset in assets:
                    await self._fetch_one(session, asset)
        except asyncio.CancelledError:
            self._emit(Progress("", DownloadState.CANCELLED, 0, 0, None))
            raise
        except Exception as exc:  # a broken connection must not kill the daemon
            _LOGGER.exception("database download failed")
            self._emit(Progress("", DownloadState.FAILED, 0, 0, str(exc)))

    async def _fetch_one(self, session: aiohttp.ClientSession, asset: Asset) -> None:
        target = self._target_dir / asset.name
        if self._is_present(asset):
            self._emit(Progress(asset.name, DownloadState.PRESENT, 0, 0, None))
            return
        partial = target.with_suffix(target.suffix + ".part")
        received = partial.stat().st_size if partial.is_file() else 0
        headers = {"Range": f"bytes={received}-"} if received else {}
        timeout = aiohttp.ClientTimeout(total=None, sock_read=_REQUEST_TIMEOUT_S)
        try:
            async with session.get(
                asset.url, headers=headers, timeout=timeout
            ) as response:
                if response.status == 416:
                    # The range is already complete; fall through to verifying.
                    received = partial.stat().st_size if partial.is_file() else 0
                elif response.status not in (200, 206):
                    self._emit(
                        Progress(
                            asset.name,
                            DownloadState.FAILED,
                            received,
                            0,
                            f"HTTP {response.status}",
                        )
                    )
                    return
                else:
                    if response.status == 200:
                        # The server ignored the range, so start over.
                        received = 0
                    total = received + (response.content_length or 0)
                    mode = "ab" if received and response.status == 206 else "wb"
                    loop = asyncio.get_running_loop()
                    last_emit = 0.0
                    self._emit(
                        Progress(
                            asset.name, DownloadState.DOWNLOADING, received, total, None
                        )
                    )
                    with partial.open(mode) as handle:
                        async for chunk in response.content.iter_chunked(_CHUNK_BYTES):
                            handle.write(chunk)
                            received += len(chunk)
                            now = loop.time()
                            if now - last_emit >= _PROGRESS_MIN_INTERVAL_S:
                                last_emit = now
                                self._emit(
                                    Progress(
                                        asset.name,
                                        DownloadState.DOWNLOADING,
                                        received,
                                        total,
                                        None,
                                    )
                                )
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, OSError) as exc:
            self._emit(
                Progress(asset.name, DownloadState.FAILED, received, 0, str(exc))
            )
            return

        self._emit(
            Progress(asset.name, DownloadState.VERIFYING, received, received, None)
        )
        try:
            actual = await asyncio.get_running_loop().run_in_executor(
                None, digest_of, partial
            )
        except OSError as exc:
            self._emit(
                Progress(asset.name, DownloadState.FAILED, received, 0, str(exc))
            )
            return
        if actual != asset.sha256:
            # A wrong file is worse than none: drop it rather than keep it.
            partial.unlink(missing_ok=True)
            self._emit(
                Progress(
                    asset.name,
                    DownloadState.FAILED,
                    received,
                    received,
                    "checksum mismatch",
                )
            )
            return
        partial.replace(target)
        self._emit(Progress(asset.name, DownloadState.DONE, received, received, None))
