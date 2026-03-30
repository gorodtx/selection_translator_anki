#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

OFFLINE_BASE_FILES = (
    "primary.sqlite3",
    "fallback.sqlite3",
    "definitions_pack.sqlite3",
)

CODE_ASSET_FILES = (
    "translator-app.tar.gz",
    "translator-extension.zip",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_local_base_paths(root: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    candidates = (
        root / "translate_logic" / "infrastructure" / "language_base" / "offline_language_base",
        root / "translate_logic" / "language_base" / "offline_language_base",
        root / "offline_language_base",
    )
    for filename in OFFLINE_BASE_FILES:
        for candidate_dir in candidates:
            candidate = candidate_dir / filename
            if candidate.is_file() and candidate.stat().st_size > 0:
                resolved[filename] = candidate
                break
        else:
            missing = ", ".join(str(path / filename) for path in candidates)
            raise FileNotFoundError(f"offline base not found for {filename}: {missing}")
    return resolved


def build_db_assets_manifest_text(digests: Mapping[str, str]) -> str:
    lines = [f"{digests[name]}  {name}" for name in OFFLINE_BASE_FILES]
    return "\n".join(lines) + "\n"


def build_db_bundle_metadata(
    *,
    repo: str,
    asset_paths: Mapping[str, Path],
    schema_version: int = 1,
) -> dict[str, Any]:
    digests = {name: sha256_file(asset_paths[name]) for name in OFFLINE_BASE_FILES}
    manifest_text = build_db_assets_manifest_text(digests)
    bundle_hash = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    bundle_tag = f"db-{bundle_hash[:12]}"
    return {
        "format_version": 1,
        "repo": repo,
        "tag": bundle_tag,
        "schema_version": schema_version,
        "manifest_asset": "db-assets.sha256",
        "assets": {
            name: {
                "name": name,
                "sha256": digests[name],
            }
            for name in OFFLINE_BASE_FILES
        },
    }


def build_release_manifest(
    *,
    repo: str,
    release_tag: str,
    assets_dir: Path,
    install_script: Path,
    db_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    code_assets = {
        name: assets_dir / name
        for name in CODE_ASSET_FILES
    }
    missing = [name for name, path in code_assets.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing code assets: {', '.join(missing)}")
    if not install_script.is_file():
        raise FileNotFoundError(f"missing install script: {install_script}")

    code_entries = {
        name: {
            "name": name,
            "sha256": sha256_file(path),
        }
        for name, path in code_assets.items()
    }
    code_entries["install.sh"] = {
        "name": "install.sh",
        "sha256": sha256_file(install_script),
    }

    return {
        "format_version": 1,
        "release": {
            "repo": repo,
            "tag": release_tag,
        },
        "code_manifest_asset": "release-assets.sha256",
        "code_assets": code_entries,
        "db_bundle": dict(db_bundle),
    }


def write_sha_manifest(path: Path, entries: Mapping[str, str], order: tuple[str, ...]) -> None:
    lines = [f"{entries[name]}  {name}" for name in order]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_build_db_bundle(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    assets_dir = Path(args.assets_dir).resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)

    source_paths = resolve_local_base_paths(root)
    copied_paths: dict[str, Path] = {}
    for name, src in source_paths.items():
        dst = assets_dir / name
        shutil.copy2(src, dst)
        copied_paths[name] = dst

    metadata = build_db_bundle_metadata(
        repo=args.repo,
        asset_paths=copied_paths,
        schema_version=args.schema_version,
    )
    write_sha_manifest(
        assets_dir / metadata["manifest_asset"],
        {name: metadata["assets"][name]["sha256"] for name in OFFLINE_BASE_FILES},
        OFFLINE_BASE_FILES,
    )
    write_json(Path(args.out_file).resolve(), metadata)
    if args.write_lock:
        write_json(Path(args.write_lock).resolve(), metadata)
    print(metadata["tag"])
    return 0


def cmd_build_release_manifest(args: argparse.Namespace) -> int:
    db_bundle = json.loads(Path(args.db_lock).read_text(encoding="utf-8"))
    payload = build_release_manifest(
        repo=args.repo,
        release_tag=args.release_tag,
        assets_dir=Path(args.assets_dir).resolve(),
        install_script=Path(args.install_script).resolve(),
        db_bundle=db_bundle,
    )
    write_json(Path(args.out_file).resolve(), payload)
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    db_bundle = sub.add_parser("build-db-bundle")
    db_bundle.add_argument("--root", default=str(_project_root()))
    db_bundle.add_argument("--repo", default="gorodtx/selection_translator_anki")
    db_bundle.add_argument("--assets-dir", required=True)
    db_bundle.add_argument("--out-file", required=True)
    db_bundle.add_argument("--write-lock")
    db_bundle.add_argument("--schema-version", type=int, default=1)
    db_bundle.set_defaults(func=cmd_build_db_bundle)

    release_manifest = sub.add_parser("build-release-manifest")
    release_manifest.add_argument("--repo", default="gorodtx/selection_translator_anki")
    release_manifest.add_argument("--release-tag", required=True)
    release_manifest.add_argument("--assets-dir", required=True)
    release_manifest.add_argument("--install-script", required=True)
    release_manifest.add_argument("--db-lock", required=True)
    release_manifest.add_argument("--out-file", required=True)
    release_manifest.set_defaults(func=cmd_build_release_manifest)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
