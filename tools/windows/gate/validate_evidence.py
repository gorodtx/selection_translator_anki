from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any
from collections.abc import Sequence

REQUIRED_FILES: tuple[str, ...] = (
    "vm-gate-checklist.md",
    "env-manifest.json",
    "logs/app.log",
    "logs/helper.log",
    "logs/ipc.log",
    "video/gate-run.mp4",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[3]
    default_schema = repo_root / "docs" / "windows" / "env-manifest.schema.json"
    parser = argparse.ArgumentParser(
        description="Validate Windows VM gate evidence bundle."
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="Path to the evidence directory.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=default_schema,
        help="Path to env-manifest JSON schema.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    evidence_dir = args.evidence_dir.resolve()
    schema_path = args.schema.resolve()
    errors: list[str] = []

    if not evidence_dir.is_dir():
        errors.append(f"Evidence directory not found: {evidence_dir}")
        _print_errors(errors)
        return 1
    if not schema_path.is_file():
        errors.append(f"Schema file not found: {schema_path}")
        _print_errors(errors)
        return 1

    _validate_required_files(evidence_dir, errors)

    manifest_path = evidence_dir / "env-manifest.json"
    schema = _load_json(schema_path, errors, label="schema")
    manifest = _load_json(manifest_path, errors, label="manifest")

    if isinstance(schema, dict) and isinstance(manifest, dict):
        _validate_with_schema(manifest, schema, "$", errors)
        _validate_manifest_cross_checks(manifest, errors)

    if errors:
        _print_errors(errors)
        return 1

    print(f"Evidence bundle is valid: {evidence_dir}")
    return 0


def _validate_required_files(evidence_dir: Path, errors: list[str]) -> None:
    for rel_path in REQUIRED_FILES:
        target = evidence_dir / rel_path
        if not target.is_file():
            errors.append(f"Missing required file: {rel_path}")
            continue
        if target.stat().st_size == 0:
            errors.append(f"Required file is empty: {rel_path}")


def _load_json(path: Path, errors: list[str], *, label: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"Failed to read {label} JSON: {path} ({exc})")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"Failed to parse {label} JSON: {path} ({exc})")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} JSON root must be an object: {path}")
        return None
    return payload


def _validate_with_schema(
    value: Any,
    schema: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object")
            return
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required key '{key}'")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected key '{key}'")
        for key, prop_schema in properties.items():
            if key in value and isinstance(prop_schema, dict):
                _validate_with_schema(value[key], prop_schema, f"{path}.{key}", errors)
        return
    if schema_type == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string")
            return
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path}: length must be >= {min_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            errors.append(f"{path}: value does not match pattern")
        const = schema.get("const")
        if const is not None and value != const:
            errors.append(f"{path}: value must be '{const}'")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            errors.append(f"{path}: value must be one of {enum}")
        return
    if schema_type == "integer":
        if not isinstance(value, int):
            errors.append(f"{path}: expected integer")
            return
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            errors.append(f"{path}: value must be >= {minimum}")
        return


def _validate_manifest_cross_checks(
    manifest: dict[str, Any], errors: list[str]
) -> None:
    run = manifest.get("run")
    if not isinstance(run, dict):
        return
    checklist = run.get("checklist")
    if checklist != "vm-gate-checklist.md":
        errors.append("$.run.checklist must be 'vm-gate-checklist.md'")


def _print_errors(errors: list[str]) -> None:
    print("Evidence validation failed:")
    for error in errors:
        print(f"- {error}")


if __name__ == "__main__":
    raise SystemExit(main())
