from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path("dev/scripts/release_metadata.py")


def test_build_db_bundle_cli_emits_lock_and_assets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    bases_dir = (
        repo_root
        / "translate_logic"
        / "infrastructure"
        / "language_base"
        / "offline_language_base"
    )
    bases_dir.mkdir(parents=True)
    (bases_dir / "primary.sqlite3").write_bytes(b"primary-db")
    (bases_dir / "fallback.sqlite3").write_bytes(b"fallback-db")
    (bases_dir / "definitions_pack.sqlite3").write_bytes(b"definitions-db")

    assets_dir = tmp_path / "dist" / "db_bundle"
    out_file = tmp_path / "db-bundle.lock.json"
    lock_file = tmp_path / "scripts" / "db-bundle.lock.json"
    lock_file.parent.mkdir(parents=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "build-db-bundle",
            "--root",
            str(repo_root),
            "--repo",
            "example/repo",
            "--assets-dir",
            str(assets_dir),
            "--out-file",
            str(out_file),
            "--write-lock",
            str(lock_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["repo"] == "example/repo"
    assert payload["tag"] == completed.stdout.strip()
    assert payload["manifest_asset"] == "db-assets.sha256"
    assert (assets_dir / "db-assets.sha256").is_file()
    assert json.loads(lock_file.read_text(encoding="utf-8")) == payload


def test_build_release_manifest_cli_includes_db_bundle_reference(tmp_path: Path) -> None:
    assets_dir = tmp_path / "dist" / "release"
    assets_dir.mkdir(parents=True)
    (assets_dir / "translator-app.tar.gz").write_bytes(b"app-archive")
    (assets_dir / "translator-extension.zip").write_bytes(b"extension-archive")

    install_script = assets_dir / "install.sh"
    install_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    db_lock = tmp_path / "db-bundle.lock.json"
    db_lock.write_text(
        json.dumps(
            {
                "format_version": 1,
                "repo": "example/repo",
                "tag": "db-123456789abc",
                "manifest_asset": "db-assets.sha256",
                "schema_version": 1,
                "assets": {
                    "primary.sqlite3": {
                        "name": "primary.sqlite3",
                        "sha256": "a" * 64,
                    },
                    "fallback.sqlite3": {
                        "name": "fallback.sqlite3",
                        "sha256": "b" * 64,
                    },
                    "definitions_pack.sqlite3": {
                        "name": "definitions_pack.sqlite3",
                        "sha256": "c" * 64,
                    },
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    out_file = tmp_path / "release-manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "build-release-manifest",
            "--repo",
            "example/repo",
            "--release-tag",
            "v9.9.9",
            "--assets-dir",
            str(assets_dir),
            "--install-script",
            str(install_script),
            "--db-lock",
            str(db_lock),
            "--out-file",
            str(out_file),
        ],
        check=True,
    )

    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["release"] == {"repo": "example/repo", "tag": "v9.9.9"}
    assert payload["code_manifest_asset"] == "release-assets.sha256"
    assert set(payload["code_assets"]) == {
        "install.sh",
        "translator-app.tar.gz",
        "translator-extension.zip",
    }
    assert payload["db_bundle"]["tag"] == "db-123456789abc"
