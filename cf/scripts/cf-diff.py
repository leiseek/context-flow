#!/usr/bin/env python3
"""cf-diff: Compare two session snapshots.

Usage:
  cf-diff.py <id1> <id2>
  cf-diff.py --project-dir /path
"""
import argparse
import json
import os
import sys
from pathlib import Path


def _diff_dicts(a, b, path=""):
    changes = []
    all_keys = set(list(a.keys()) + list(b.keys()))
    for k in all_keys:
        kpath = f"{path}.{k}" if path else k
        va = a.get(k)
        vb = b.get(k)
        if type(va) != type(vb) and va is not None and vb is not None:
            changes.append((kpath, f"type changed: {type(va).__name__} -> {type(vb).__name__}", str(va)[:200], str(vb)[:200]))
        elif isinstance(va, dict) and isinstance(vb, dict):
            changes.extend(_diff_dicts(va, vb, kpath))
        elif isinstance(va, list) and isinstance(vb, list):
            if len(va) != len(vb):
                changes.append((kpath, f"length: {len(va)} -> {len(vb)}", "", ""))
            elif va != vb:
                changes.append((kpath, "different content", str(va)[:300], str(vb)[:300]))
        elif va != vb:
            changes.append((kpath, "changed", str(va)[:300], str(vb)[:300]))
    return changes


def format_summary(usf):
    s = usf.get("source", {})
    sn = usf.get("snapshot", {})
    fs = usf.get("file_state", {})
    ci = usf.get("current_intent", {})
    lines = []
    lines.append(f"  Tool: {s.get('tool', '?')}")
    lines.append(f"  Model: {s.get('model', '?')}")
    lines.append(f"  Session: {sn.get('session_id', '?')[:16]}")
    lines.append(f"  Timestamp: {sn.get('timestamp', '?')}")
    lines.append(f"  Messages: {sn.get('total_messages', 0)}")
    lines.append(f"  Branch: {fs.get('current_branch', '?')}")
    lines.append(f"  Uncommitted: {fs.get('uncommitted_count', 0)}")
    lines.append(f"  Modified files: {len(fs.get('modified', []) or [])}")
    lines.append(f"  Created files: {len(fs.get('created', []) or [])}")
    lines.append(f"  Deleted files: {len(fs.get('deleted', []) or [])}")
    if ci.get("task"):
        lines.append(f"  Task: {ci['task'][:80]}")
    return "\n".join(lines)


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Compare two session snapshots")
    parser.add_argument("id1", help="First snapshot ID or path")
    parser.add_argument("id2", nargs="?", help="Second snapshot ID or path (default: latest)")
    parser.add_argument("--project-dir", default=None, help="Project directory with .session-bridge")
    parser.add_argument("--global", dest="use_global", action="store_true", help="Use ~/.session-bridge/")
    args = parser.parse_args()

    project_dir = Path(args.project_dir or Path.cwd()).resolve()

    if args.use_global:
        import hashlib
        proj_hash = hashlib.sha256(str(project_dir).encode()).hexdigest()[:32]
        bridge_dir = Path.home() / ".session-bridge" / proj_hash
    else:
        bridge_dir = project_dir / ".session-bridge"

    def resolve_id(sid):
        p = bridge_dir / sid
        if p.exists() and (p / "session.usf.json").exists():
            return p
        candidates = sorted(
            [d for d in bridge_dir.iterdir() if d.is_dir() and (d / "session.usf.json").exists()],
            key=lambda d: d.stat().st_mtime, reverse=True
        )
        if sid == "latest" and candidates:
            return candidates[0]
        for c in candidates:
            if sid in c.name:
                return c
        return None

    snap1 = resolve_id(args.id1)
    if not snap1:
        print(f"Error: snapshot '{args.id1}' not found", file=sys.stderr)
        sys.exit(1)

    id2 = args.id2 or "latest"
    snap2 = resolve_id(id2)
    if not snap2:
        print(f"Error: snapshot '{id2}' not found", file=sys.stderr)
        sys.exit(1)

    if snap1 == snap2:
        print("Same snapshot \u2014 nothing to diff")
        sys.exit(0)

    usf1 = json.loads((snap1 / "session.usf.json").read_text(encoding="utf-8"))
    usf2 = json.loads((snap2 / "session.usf.json").read_text(encoding="utf-8"))

    print(f"Diff: {snap1.name}  vs  {snap2.name}")
    print("=" * 72)
    print()
    print("--- Snapshot 1 ---")
    print(format_summary(usf1))
    print()
    print("--- Snapshot 2 ---")
    print(format_summary(usf2))
    print()

    changes = _diff_dicts(usf1, usf2)
    if changes:
        print("--- Changes ---")
        for path, action, old, new in changes:
            print(f"  [{action}] {path}")
            if old or new:
                print(f"    was: {old[:120]}")
                print(f"    now: {new[:120]}")
        print()
        print(f"Total: {len(changes)} difference(s)")
    else:
        print("No differences found")


if __name__ == "__main__":
    main()
