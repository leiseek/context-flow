#!/usr/bin/env python3
"""cf-load: Read a saved session snapshot and generate context document.

Usage:
  cf-load.py                          # pick latest snapshot
  cf-load.py latest                   # same as above
  cf-load.py opencode-abc123-def456   # specific snapshot ID
  cf-load.py --inject                 # write to .session-bridge/load-context.md
  cf-load.py --brief                  # condensed output
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def _home():
    return Path.home()


def make_context(usf, detailed=True):
    s = usf["source"]
    sn = usf["snapshot"]
    fs = usf["file_state"]
    ci = usf["current_intent"]
    tc = usf.get("tool_calls", {})
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    lines.append("# ContextFlow Load \u2014 Session Context")
    lines.append(f"*Generated: {now}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## Session Overview")
    lines.append(f"- **Source Tool:** {s['tool']}  ")
    lines.append(f"- **Source Model:** {s.get('model', 'unknown')}  ")
    lines.append(f"- **Session ID:** {sn['session_id']}  ")
    lines.append(f"- **Timestamp:** {sn['timestamp']}  ")
    lines.append(f"- **Total Messages:** {sn['total_messages']}  ")
    lines.append(f"- **Total Tool Calls:** {sn['total_tool_calls']}  ")
    lines.append("")

    lines.append("## Current Intent")
    if ci.get("task"):
        lines.append(f"- **Active Task:** {ci['task']}  ")
    if ci.get("completed"):
        lines.append(f"- **Completed:** {', '.join(ci['completed'][:10])}  ")
    if ci.get("in_progress"):
        lines.append(f"- **In Progress:** {', '.join(ci['in_progress'][:5])}  ")
    if ci.get("next_steps"):
        lines.append(f"- **Next Steps:** {', '.join(ci['next_steps'][:10])}  ")
    if ci.get("blockers"):
        lines.append(f"- **Blockers:** {', '.join(ci['blockers'][:5])}  ")
    lines.append(f"- **Confidence:** {ci.get('confidence', 'N/A')}  ")
    lines.append("")

    lines.append("## File State")
    branch = fs.get("current_branch") or "unknown"
    lines.append(f"- **Branch:** `{branch}`  ")
    lines.append(f"- **Uncommitted Changes:** {fs.get('uncommitted_count', 0)}  ")
    modified = fs.get("modified", []) or []
    created = fs.get("created", []) or []
    deleted = fs.get("deleted", []) or []
    if modified:
        lines.append(f"- **Modified Files ({len(modified)}):**")
        for m in modified[:20]:
            lines.append(f"  - `{m['path']}`")
    if created:
        lines.append(f"- **Created Files ({len(created)}):**")
        for c in created[:10]:
            lines.append(f"  - `{c['path']}`")
    if deleted:
        lines.append(f"- **Deleted Files ({len(deleted)}):**")
        for d in deleted[:10]:
            lines.append(f"  - `{d}`")
    lines.append("")

    if detailed and modified and modified[0].get("diff"):
        lines.append("### Diff (first modified file)")
        diff = modified[0]["diff"]
        if len(diff) > 4000:
            diff = diff[:4000] + "\n... [truncated]"
        lines.append("```diff")
        lines.append(diff)
        lines.append("```")
        lines.append("")

    conversation = usf.get("conversation", []) or []
    if conversation:
        lines.append("## Recent Conversation")
        lines.append(f"*{len(conversation)} messages total, showing last {min(len(conversation), 20)}:*")
        lines.append("")
        for msg in conversation[-20:]:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"**{role}:** {content}")
            lines.append("")
        lines.append("")

    decisions = usf.get("decisions", []) or []
    if decisions:
        lines.append("## Design Decisions")
        for d in decisions[:15]:
            lines.append(f"- **{d['topic']}**: chose `{d['chosen']}`")
            if d.get("rejected"):
                lines.append(f"  - Rejected: {', '.join(d['rejected'][:5])}")
            if d.get("reasoning"):
                lines.append(f"  - Reasoning: {d['reasoning']}")
        lines.append("")

    if tc:
        compatible = tc.get("compatible", []) or []
        incompatible = tc.get("incompatible", []) or []
        lines.append("## Tool Call Compatibility")
        lines.append(f"- **Compatible tools used ({len(compatible)}):** standard across tools")
        if compatible:
            tool_counts = {}
            for t in compatible:
                tn = t.get("tool", "unknown")
                tool_counts[tn] = tool_counts.get(tn, 0) + 1
            for tn, count in sorted(tool_counts.items()):
                lines.append(f"  - `{tn}`: {count} calls")
        lines.append(f"- **Incompatible tools used ({len(incompatible)}):** tool-specific, needs review")
        for t in incompatible[:10]:
            lines.append(f"  - `{t.get('tool', 'unknown')}`: {t.get('result_summary', '')}")
        lines.append("")

    lines.append("---")
    lines.append("*End of ContextFlow loaded context*")

    return "\n".join(lines)


def find_latest_snapshot(bridge_dir):
    bridge = Path(bridge_dir)
    if not bridge.exists():
        return None
    snapshots = sorted(bridge.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for snap in snapshots:
        if snap.is_dir() and (snap / "session.usf.json").exists():
            return snap
    return None


def read_usf(snapshot_dir):
    usf_path = Path(snapshot_dir) / "session.usf.json"
    if not usf_path.exists():
        print(f"Error: session.usf.json not found in {snapshot_dir}", file=sys.stderr)
        sys.exit(1)
    return json.loads(usf_path.read_text(encoding="utf-8"))


def main():
    # Ensure UTF-8 output on Windows (avoids GBK encoding errors on Chinese locale)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Load session context from USF snapshot")
    parser.add_argument("snapshot_id", nargs="?", default="latest", help="Snapshot ID or 'latest'")
    parser.add_argument("--project-dir", default=None, help="Project directory with .session-bridge")
    parser.add_argument("--global", dest="use_global", action="store_true", help="Use ~/.session-bridge/")
    parser.add_argument("--inject", action="store_true", help="Write context to .session-bridge/load-context.md")
    parser.add_argument("--brief", action="store_true", help="Output brief context (no diffs or full conversation)")
    args = parser.parse_args()

    project_dir = Path(args.project_dir or Path.cwd()).resolve()

    if args.use_global:
        proj_hash = hashlib.sha256(str(project_dir).encode()).hexdigest()[:32]
        bridge_dir = _home() / ".session-bridge" / proj_hash
    else:
        bridge_dir = project_dir / ".session-bridge"

    if args.snapshot_id == "latest":
        snapshot_dir = find_latest_snapshot(bridge_dir)
        if snapshot_dir is None:
            print("Error: No snapshots found", file=sys.stderr)
            sys.exit(1)
    else:
        snapshot_dir = bridge_dir / args.snapshot_id
        if not snapshot_dir.exists():
            print(f"Error: Snapshot '{args.snapshot_id}' not found in {bridge_dir}", file=sys.stderr)
            sys.exit(1)

    usf = read_usf(snapshot_dir)
    context = make_context(usf, detailed=not args.brief)

    if args.inject:
        inject_path = bridge_dir / "load-context.md"
        inject_path.write_text(context, encoding="utf-8")
        print(f"Injected context to {inject_path}", file=sys.stderr)
    else:
        sys.stdout.write(context)
        sys.stdout.write("\n")

    print(f"\nLoaded from: {snapshot_dir.name}", file=sys.stderr)
    print(f"  Tool: {usf['source']['tool']}", file=sys.stderr)
    print(f"  Model: {usf['source'].get('model', 'unknown')}", file=sys.stderr)
    print(f"  Messages: {usf['snapshot']['total_messages']}", file=sys.stderr)
    print(f"  Decisions: {len(usf.get('decisions', []))}", file=sys.stderr)


if __name__ == "__main__":
    main()
