#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import zipfile

STABLE_UUID = "translator@com.translator.desktop"
DEV_UUID = "translator-dev@com.translator.desktop"
STABLE_SCHEMA_ID = "org.gnome.shell.extensions.translator"
DEV_SCHEMA_ID = "org.gnome.shell.extensions.translator.dev"
STABLE_SCHEMA_PATH = "/org/gnome/shell/extensions/translator/"
DEV_SCHEMA_PATH = "/org/gnome/shell/extensions/translator-dev/"
DEV_BUS_NAME = "com.translator.desktop.dev"
DBUS_INTERFACE = "com.translator.desktop"
DBUS_OBJECT_PATH = "/com/translator/desktop"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build isolated dev GNOME extension package."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root",
    )
    parser.add_argument(
        "--output-zip",
        type=Path,
        default=None,
        help="Output ZIP path (default: dev/dist/dev/translator-dev-extension.zip)",
    )
    return parser.parse_args()


def update_metadata(metadata_path: Path) -> None:
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["uuid"] = DEV_UUID
    payload["name"] = "Translator (Dev)"
    payload["settings-schema"] = DEV_SCHEMA_ID
    payload["x-translator-bus-name"] = DEV_BUS_NAME
    payload["x-translator-dbus-interface"] = DBUS_INTERFACE
    payload["x-translator-object-path"] = DBUS_OBJECT_PATH
    metadata_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )


def update_schema(schema_path: Path) -> None:
    content = schema_path.read_text(encoding="utf-8")
    content = content.replace(STABLE_SCHEMA_ID, DEV_SCHEMA_ID)
    content = content.replace(STABLE_SCHEMA_PATH, DEV_SCHEMA_PATH)
    schema_path.write_text(content, encoding="utf-8")


def build_zip(extension_root: Path, output_zip: Path) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()
    with zipfile.ZipFile(
        output_zip, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(extension_root.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(extension_root.parent)
            archive.write(path, rel.as_posix())


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    src_dir = root / "gnome_extension" / STABLE_UUID
    dist_dir = root / "dev" / "dist" / "dev" / "extension"
    out_zip = args.output_zip or (
        root / "dev" / "dist" / "dev" / "translator-dev-extension.zip"
    )

    if not src_dir.is_dir():
        raise SystemExit(f"source extension not found: {src_dir}")

    target_dir = dist_dir / DEV_UUID
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, target_dir)

    update_metadata(target_dir / "metadata.json")
    update_schema(
        target_dir / "schemas" / "org.gnome.shell.extensions.translator.gschema.xml"
    )
    build_zip(target_dir, out_zip)

    print(f"dev extension dir: {target_dir}")
    print(f"dev extension zip: {out_zip}")


if __name__ == "__main__":
    main()
