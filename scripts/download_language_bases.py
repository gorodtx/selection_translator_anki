"""Download offline assets from GitHub Releases.

This repository keeps the runtime small by **not** storing large offline assets in
git. Instead, they are distributed as GitHub Release assets and downloaded
locally into:

- `offline_assets/` (required OPUS-MT CT2 model files)
- `offline_language_base/` (optional SQLite language bases with examples)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
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
            "User-Agent": "translator-offline-assets-downloader",
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


def _is_offline_assets_ready(assets_dir: Path) -> bool:
    expected = assets_dir / "ct2" / "opus_mt" / "en-ru" / "model.bin"
    return expected.exists()


def _safe_extract_zip(*, archive: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()

    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if not members:
            raise RuntimeError(f"empty zip archive: {archive}")

        # Normalize path separators and leading "./".
        names = [m.filename.replace("\\", "/").lstrip("./") for m in members]

        # Common packaging formats:
        # - zip contains `ct2/...`
        # - zip contains `offline_assets/ct2/...` (when zipped as a folder)
        strip_prefix = None
        if all(name.startswith("offline_assets/") for name in names):
            strip_prefix = "offline_assets/"

        for member, raw_name in zip(members, names, strict=True):
            name = raw_name
            if strip_prefix and name.startswith(strip_prefix):
                name = name.removeprefix(strip_prefix)
            name = name.lstrip("/")
            if not name:
                continue

            out_path = (dest_dir / name).resolve()
            if dest_root not in out_path.parents and out_path != dest_root:
                raise RuntimeError(
                    f"refusing to extract outside destination: {member.filename}"
                )

            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)


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
        dest="language_base_dir",
        default=str(_project_root() / "offline_language_base"),
        help="Directory to place downloaded sqlite files (default: %(default)s)",
    )
    # Alias (preferred name), but keep --out-dir for compatibility.
    p.add_argument(
        "--language-base-dir",
        dest="language_base_dir",
        default=str(_project_root() / "offline_language_base"),
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--offline-assets-dir",
        default=str(_project_root() / "offline_assets"),
        help="Directory to place downloaded model files (default: %(default)s)",
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
        "--offline-assets-asset",
        default="offline_assets.zip",
        help="Offline model archive asset name in release (default: %(default)s)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite local files if they already exist.",
    )
    p.add_argument(
        "--skip-model",
        action="store_true",
        help="Skip downloading offline_assets/ (model files).",
    )
    p.add_argument(
        "--skip-bases",
        action="store_true",
        help="Skip downloading offline_language_base/ (sqlite language bases).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    if not args.skip_bases:
        out_dir = Path(args.language_base_dir)
        specs = [
            DownloadSpec(args.primary_asset, out_dir / "primary.sqlite3"),
            DownloadSpec(args.fallback_asset, out_dir / "fallback.sqlite3"),
        ]
        for spec in specs:
            url = _release_asset_url(
                repo=args.repo,
                tag=args.tag,
                asset_name=spec.asset_name,
            )
            _download_file(url=url, dest=spec.dest_path, force=args.force)

    if not args.skip_model:
        assets_dir = Path(args.offline_assets_dir)
        if _is_offline_assets_ready(assets_dir) and not args.force:
            print(f"skip (ready): {assets_dir}", file=sys.stderr)
            return 0

        archive_name = args.offline_assets_asset
        # Download next to the destination directory so we can write atomically,
        # then delete the archive after extraction.
        archive_path = assets_dir.parent / archive_name
        url = _release_asset_url(
            repo=args.repo,
            tag=args.tag,
            asset_name=archive_name,
        )
        _download_file(url=url, dest=archive_path, force=True)
        _safe_extract_zip(archive=archive_path, dest_dir=assets_dir)
        archive_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
