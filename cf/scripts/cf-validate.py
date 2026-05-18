#!/usr/bin/env python3
"""cf-validate: Validate a USF file against the schema.

Usage:
  cf-validate.py <snapshot-id>
  cf-validate.py --file path/to/session.usf.json
  cf-validate.py --project-dir /path
"""
import argparse
import json
import os
import sys
from pathlib import Path


REQUIRED_TOP = ["version", "source", "snapshot", "file_state", "conversation", "tool_calls", "decisions", "current_intent"]

REQUIRED_SOURCE = ["tool", "model"]
VALID_TOOLS = ["opencode", "claude-code", "codex", "cursor", "copilot-cli"]

REQUIRED_SNAPSHOT = ["timestamp", "session_id", "duration_minutes", "total_messages", "total_tool_calls"]

REQUIRED_FILE_STATE = ["modified", "created", "deleted", "current_branch", "uncommitted_count"]


def validate(usf, path=""):
    errors = []
    warnings = []

    if not isinstance(usf, dict):
        errors.append(f"{path}: root must be an object")
        return errors, warnings

    for field in REQUIRED_TOP:
        if field not in usf:
            errors.append(f"{path}: missing required field '{field}'")

    s = usf.get("source", {})
    if isinstance(s, dict):
        for field in REQUIRED_SOURCE:
            if field not in s:
                errors.append(f"{path}.source: missing '{field}'")
        tool = s.get("tool")
        if tool and tool not in VALID_TOOLS:
            warnings.append(f"{path}.source.tool: '{tool}' not in standard tool list {VALID_TOOLS}")
    else:
        errors.append(f"{path}.source: must be an object")

    sn = usf.get("snapshot", {})
    if isinstance(sn, dict):
        for field in REQUIRED_SNAPSHOT:
            if field not in sn:
                errors.append(f"{path}.snapshot: missing '{field}'")
        ts = sn.get("timestamp", "")
        if ts and not isinstance(ts, str):
            errors.append(f"{path}.snapshot.timestamp: must be a string")
    else:
        errors.append(f"{path}.snapshot: must be an object")

    fs = usf.get("file_state", {})
    if isinstance(fs, dict):
        for field in REQUIRED_FILE_STATE:
            if field not in fs:
                errors.append(f"{path}.file_state: missing '{field}'")
        for arr_field in ("modified", "created", "deleted"):
            val = fs.get(arr_field, [])
            if not isinstance(val, list):
                errors.append(f"{path}.file_state.{arr_field}: must be an array")
    else:
        errors.append(f"{path}.file_state: must be an object")

    conv = usf.get("conversation", [])
    if isinstance(conv, list):
        for i, msg in enumerate(conv):
            if not isinstance(msg, dict):
                errors.append(f"{path}.conversation[{i}]: must be an object")
            elif "role" not in msg or "content" not in msg:
                errors.append(f"{path}.conversation[{i}]: missing 'role' or 'content'")
    else:
        errors.append(f"{path}.conversation: must be an array")

    ver = usf.get("version", "")
    if ver and not isinstance(ver, str):
        errors.append(f"{path}.version: must be a string")

    return errors, warnings


def main():
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

    errors, warnings = validate(usf)

    print(f"Validating: {usf_path}")
    print(f"  Version: {usf.get('version', 'N/A')}")
    print(f"  Tool: {usf.get('source', {}).get('tool', 'N/A')}")
    print(f"  Session: {usf.get('snapshot', {}).get('session_id', 'N/A')[:16]}")
    print()

    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print(f"\n  FAILED \u2014 {len(errors)} error(s)")
    else:
        print("  \u2713 All required fields present")

    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")

    if not errors:
        print("\n  \u2713 Valid")


if __name__ == "__main__":
    main()
