#!/usr/bin/env python3
"""cf-status: List available session snapshots.

Usage:
  cf-status.py
  cf-status.py --project-dir /path
  cf-status.py --global
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def _home():
    return Path.home()


def format_size(bytes_val):
    if bytes_val < 1024:
        return f"{bytes_val}B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f}KB"
    else:
        return f"{bytes_val / (1024 * 1024):.1f}MB"


def format_age(ts):
    try:
        mtime = datetime.fromtimestamp(ts)
        delta = datetime.now() - mtime
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return "just now"
    except Exception:
        return ""


def list_snapshots(bridge_dir):
    bridge = Path(bridge_dir)
    if not bridge.exists():
        return []

    snapshots = []
    for entry in sorted(bridge.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not entry.is_dir():
            continue
        usf_path = entry / "session.usf.json"
        summary_path = entry / "session.summary.md"
        if not usf_path.exists():
            continue

        usf_size = usf_path.stat().st_size
        mtime = usf_path.stat().st_mtime

        info = {
            "id": entry.name,
            "path": str(entry),
            "usf_size": usf_size,
            "summary_size": summary_path.stat().st_size if summary_path.exists() else 0,
            "mtime": mtime,
        }

        try:
            usf = json.loads(usf_path.read_text(encoding="utf-8"))
            source = usf.get("source", {})
            snapshot = usf.get("snapshot", {})
            info["tool"] = source.get("tool", "?")
            info["model"] = source.get("model", "?")
            info["messages"] = snapshot.get("total_messages", 0)
            info["tool_calls"] = snapshot.get("total_tool_calls", 0)
            intent = usf.get("current_intent", {})
            info["task"] = (intent.get("task") or "")[:60]
            info["decisions"] = len(usf.get("decisions", []))
        except (json.JSONDecodeError, KeyError):
            info["tool"] = "?"
            info["model"] = "?"
            info["messages"] = 0
            info["tool_calls"] = 0
            info["task"] = ""
            info["decisions"] = 0

        snapshots.append(info)

    return snapshots


def main():
    parser = argparse.ArgumentParser(description="List session snapshots")
    parser.add_argument("--project-dir", default=None, help="Project directory")
    parser.add_argument("--global", dest="use_global", action="store_true", help="Use ~/.session-bridge/")
    args = parser.parse_args()

    project_dir = Path(args.project_dir or Path.cwd()).resolve()

    if args.use_global:
        import hashlib
        proj_hash = hashlib.sha256(str(project_dir).encode()).hexdigest()[:32]
        bridge_dir = _home() / ".session-bridge" / proj_hash
    else:
        bridge_dir = project_dir / ".session-bridge"

    snapshots = list_snapshots(bridge_dir)

    if not snapshots:
        print(f"No snapshots found in {bridge_dir}")
        sys.exit(0)

    print(f"Snapshots in {bridge_dir}/")
    print(f"{'ID':<50} {'Tool':<14} {'Msgs':<6} {'Size':<10} {'Age':<12} Task")
    print("-" * 120)
    for s in snapshots:
        snap_id = s["id"][:48]
        tool = s["tool"]
        msgs = str(s["messages"])
        size = format_size(s["usf_size"])
        age = format_age(s["mtime"])
        task = s["task"]
        print(f"{snap_id:<50} {tool:<14} {msgs:<6} {size:<10} {age:<12} {task}")

    print(f"\nTotal: {len(snapshots)} snapshot(s)")


if __name__ == "__main__":
    main()
