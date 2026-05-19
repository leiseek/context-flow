#!/usr/bin/env python3
"""cf-validate: Validate a USF file against the schema.

Reads cf/schemas/usf-schema.json dynamically — validation rules stay in sync
with the schema automatically.

Usage:
  cf-validate.py <snapshot-id>
  cf-validate.py --file path/to/session.usf.json
  cf-validate.py --project-dir /path
"""
import argparse
import json
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "usf-schema.json"


def load_schema():
    if not SCHEMA_PATH.exists():
        print(f"Error: schema file not found: {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _check_type(value, expected, path, errors):
    if isinstance(expected, list):
        if not any(_type_match(value, t) for t in expected):
            type_names = "/".join(expected)
            errors.append(f"{path}: expected type {type_names}, got {type(value).__name__}")
    else:
        if not _type_match(value, expected):
            errors.append(f"{path}: expected type {expected}, got {type(value).__name__}")


def _type_match(value, type_name):
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "null":
        return value is None
    return True


def _validate_enum(value, enum_values, path, errors):
    if value not in enum_values:
        errors.append(f"{path}: value '{value}' not in {enum_values}")


def _validate_minimum(value, minimum, path, errors):
    if isinstance(value, (int, float)) and value < minimum:
        errors.append(f"{path}: value {value} is below minimum {minimum}")


def _validate_maximum(value, maximum, path, errors):
    if isinstance(value, (int, float)) and value > maximum:
        errors.append(f"{path}: value {value} exceeds maximum {maximum}")


def validate(data, schema, path=""):
    errors = []
    warnings = []

    if not isinstance(data, dict):
        errors.append(f"{path}: root must be an object")
        return errors, warnings

    # Required fields
    for field in schema.get("required", []):
        if field not in data:
            errors.append(f"{path}: missing required field '{field}'")

    properties = schema.get("properties", {})

    for key, prop_schema in properties.items():
        if key not in data:
            continue
        value = data[key]
        kpath = f"{path}.{key}" if path else key

        prop_type = prop_schema.get("type")
        if prop_type:
            _check_type(value, prop_type, kpath, errors)

        if "enum" in prop_schema and isinstance(value, str):
            _validate_enum(value, prop_schema["enum"], kpath, errors)

        if "minimum" in prop_schema:
            _validate_minimum(value, prop_schema["minimum"], kpath, errors)

        if "maximum" in prop_schema:
            _validate_maximum(value, prop_schema["maximum"], kpath, errors)

        # Recurse into objects
        if isinstance(value, dict) and "properties" in prop_schema:
            sub_errors, sub_warnings = validate(value, prop_schema, kpath)
            errors.extend(sub_errors)
            warnings.extend(sub_warnings)

        # Recurse into arrays with items schema
        if isinstance(value, list) and "items" in prop_schema:
            items_schema = prop_schema["items"]
            if isinstance(items_schema, dict):
                for i, item in enumerate(value):
                    ipath = f"{kpath}[{i}]"
                    if isinstance(items_schema.get("type"), str) and items_schema["type"] == "object":
                        if not isinstance(item, dict):
                            errors.append(f"{ipath}: must be an object")
                        else:
                            # Check required fields in items
                            for req in items_schema.get("required", []):
                                if req not in item:
                                    errors.append(f"{ipath}: missing '{req}'")
                            for ik, ischema in items_schema.get("properties", {}).items():
                                if ik in item:
                                    ival = item[ik]
                                    if "enum" in ischema and isinstance(ival, str):
                                        _validate_enum(ival, ischema["enum"], f"{ipath}.{ik}", errors)

        # Non-standard tool name in source.tool → warning
        if key == "tool" and "enum" in prop_schema and isinstance(value, str) and value not in prop_schema["enum"]:
            warnings.append(f"{kpath}: '{value}' not in standard tool list {prop_schema['enum']}")

    return errors, warnings


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Validate USF file against schema")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("snapshot_id", nargs="?", help="Snapshot ID in .session-bridge/")
    group.add_argument("--file", help="Direct path to a session.usf.json file")
    parser.add_argument("--project-dir", default=None, help="Project directory with .session-bridge")
    args = parser.parse_args()

    if args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"Error: file not found: {fpath}", file=sys.stderr)
            sys.exit(1)
        usf_path = fpath
    elif args.snapshot_id:
        project_dir = Path(args.project_dir or Path.cwd()).resolve()
        bridge_dir = project_dir / ".session-bridge"
        if args.snapshot_id == "latest":
            candidates = sorted(
                [d for d in bridge_dir.iterdir() if d.is_dir() and (d / "session.usf.json").exists()],
                key=lambda d: d.stat().st_mtime, reverse=True
            )
            if not candidates:
                print("Error: no snapshots found", file=sys.stderr)
                sys.exit(1)
            usf_path = candidates[0] / "session.usf.json"
        else:
            usf_path = bridge_dir / args.snapshot_id / "session.usf.json"
            if not usf_path.exists():
                print(f"Error: snapshot '{args.snapshot_id}' not found in {bridge_dir}", file=sys.stderr)
                sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

    try:
        usf = json.loads(usf_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {usf_path}: {e}", file=sys.stderr)
        sys.exit(1)

    schema = load_schema()
    errors, warnings = validate(usf, schema)

    print(f"Validating: {usf_path}")
    print(f"  Schema: {SCHEMA_PATH}")
    print(f"  Version: {usf.get('version', 'N/A')}")
    print(f"  Tool: {usf.get('source', {}).get('tool', 'N/A')}")
    print(f"  Session: {usf.get('snapshot', {}).get('session_id', 'N/A')[:16]}")
    print()

    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print(f"\n  FAILED — {len(errors)} error(s)")
    else:
        print("  All required fields present, types valid")

    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")

    if not errors:
        print("\n  Valid")


if __name__ == "__main__":
    main()
