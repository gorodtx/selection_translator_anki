"""Download offline language bases from GitHub Releases.

The SQLite language bases are intentionally not stored in git (too large).
They are distributed as GitHub Release assets and downloaded locally into
`offline_language_base/`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadSpec:
    asset_name: str
    dest_path: Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _release_asset_url(*, repo: str, tag: str | None, asset_name: str) -> str:
    if tag is None:
        return f"https://github.com/{repo}/releases/latest/download/{asset_name}"
    return f"https://github.com/{repo}/releases/download/{tag}/{asset_name}"


def _download_file(*, url: str, dest: Path, force: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    if dest.exists() and not force:
        print(f"skip (exists): {dest}", file=sys.stderr)
        return

    if tmp.exists():
        tmp.unlink()

    req = urllib.request.Request(
        url,
        headers={
            # GitHub will 403 some requests without a UA.
            "User-Agent": "translator-offline-bases-downloader",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            with tmp.open("wb") as f:
                shutil.copyfileobj(resp, f, length=1024 * 1024)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"download failed: {url} ({e.code} {e.reason})") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"download failed: {url} ({e.reason})") from e

    tmp.replace(dest)
    print(f"downloaded: {dest}", file=sys.stderr)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--repo",
        default="igor3204/selection_translator_anki",
        help="GitHub repo in owner/name form (default: %(default)s)",
    )
    p.add_argument(
        "--tag",
        default=None,
        help=(
            "Release tag to download from. If omitted, downloads from the latest "
            "release."
        ),
    )
    p.add_argument(
        "--out-dir",
        default=str(_project_root() / "offline_language_base"),
        help="Directory to place downloaded sqlite files (default: %(default)s)",
    )
    p.add_argument(
        "--primary-asset",
        default="primary.sqlite3",
        help="Primary DB asset name in release (default: %(default)s)",
    )
    p.add_argument(
        "--fallback-asset",
        default="fallback.sqlite3",
        help="Fallback DB asset name in release (default: %(default)s)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite local files if they already exist.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    out_dir = Path(args.out_dir)
    specs = [
        DownloadSpec(args.primary_asset, out_dir / "primary.sqlite3"),
        DownloadSpec(args.fallback_asset, out_dir / "fallback.sqlite3"),
    ]

    for spec in specs:
        url = _release_asset_url(
            repo=args.repo, tag=args.tag, asset_name=spec.asset_name
        )
        _download_file(url=url, dest=spec.dest_path, force=args.force)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
