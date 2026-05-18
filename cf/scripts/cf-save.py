#!/usr/bin/env python3
"""cf-save: Save current session context to .session-bridge/ (no LLM required).

Cross-platform: works on Linux, macOS, Windows.

Usage:
  cf-save.py
  cf-save.py --label my-label
  cf-save.py --global
  cf-save.py --tool claude-code --session-id abc123
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _home():
    return Path.home()


RETENTION_DAYS = 30


TOOL_PROJECT_MARKERS = {
    "OPENCODE": [".opencode.json", ".opencode.jsonc"],
    "CLAUDECODE": ["CLAUDE.md", "CLAUDE.txt"],
    "CURSOR": [".cursorrules"],
    "CODEX": [".codex"],
    "COPILOT_CLI": [".github/copilot-instructions.md", ".github/copilot"],
}

TOOL_SESSION_PATHS = {
    "OPENCODE": [_home() / ".local/share/opencode/opencode.db",
                  _home() / "AppData/Local/opencode/opencode.db"],
    "CLAUDECODE": [_home() / ".claude/projects"],
    "CURSOR": [_home() / ".cursor/projects",
               _home() / ".cursor"],
    "CODEX": [_home() / ".codex/sessions"],
    "COPILOT_CLI": [_home() / ".copilot/session-state"],
}

TOOL_NAMES = {
    "OPENCODE": "opencode",
    "CLAUDECODE": "claude-code",
    "CURSOR": "cursor",
    "CODEX": "codex",
    "COPILOT_CLI": "copilot-cli",
}


SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|private[_-]?key|passwd)[=: ].{4,120}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"),
    re.compile(r"(?i)(-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----)"),
]


def redact_line(line):
    for p in SENSITIVE_PATTERNS:
        line = p.sub("[REDACTED]", line)
    return line


def redact_text(text):
    return "\n".join(redact_line(l) for l in text.split("\n"))


def git_cmd(project_dir, *args):
    try:
        r = subprocess.run(["git"] + list(args), capture_output=True, text=True,
                           cwd=str(project_dir), timeout=5)
        return r.stdout.strip() or None
    except Exception:
        return None


def get_git_state(project_dir):
    pd = Path(project_dir)
    branch = git_cmd(pd, "rev-parse", "--abbrev-ref", "HEAD")
    diff = git_cmd(pd, "diff", "--stat")
    diff_full = git_cmd(pd, "diff")
    status_output = git_cmd(pd, "status", "--porcelain")
    uncommitted = len([l for l in (status_output or "").split("\n") if l.strip()])

    modified = []
    if diff:
        for line in diff.split("\n"):
            parts = line.strip().split("|")
            if parts and parts[0].strip():
                modified.append({"path": parts[0].strip(), "diff": (diff_full or "")[:2000]})

    created, deleted = [], []
    if status_output:
        for line in status_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            status = line[:2].strip()
            path = line[3:].strip()
            if status in ("A", "??"):
                created.append({"path": path})
            elif status == "D":
                deleted.append(path)

    return {
        "branch": branch,
        "uncommitted": uncommitted,
        "modified": modified[:50],
        "created": created[:20],
        "deleted": deleted[:20],
    }


def get_project_hash(project_dir):
    return hashlib.sha256(str(project_dir).encode()).hexdigest()[:32]


def detect_tool(project_dir):
    pd = Path(project_dir)
    for tool_id, markers in TOOL_PROJECT_MARKERS.items():
        for m in markers:
            if (pd / m).exists():
                return tool_id
    for tool_id, paths in TOOL_SESSION_PATHS.items():
        for p in paths:
            if p.exists():
                return tool_id
    return None


def build_usf(tool, session_id, conversation, tool_calls, git):
    now = datetime.now(timezone.utc).isoformat()
    conv_text = " ".join(c["content"] for c in conversation[-10:])

    decisions = []
    kw_patterns = [r"(?:I\s+(?:decided|chose|selected|picked|went with|abandoned|rejected|preferred)\s+[^.!?]+)"]
    for pat in kw_patterns:
        for m in re.finditer(pat, conv_text, re.IGNORECASE):
            topic = m.group()[:80]
            decisions.append({"topic": topic, "chosen": m.group()[:80], "rejected": [], "reasoning": ""})

    last_msgs = [c["content"] for c in conversation[-4:] if c["role"] == "user"]
    intent = {
        "task": last_msgs[-1][:200] if last_msgs else None,
        "completed": [m["path"] for m in (git["modified"] or [])[:5]],
        "in_progress": [last_msgs[-1][:100]] if last_msgs else [],
        "next_steps": [],
        "blockers": [],
        "confidence": 0.5,
    }

    compatible_tools = {"Bash", "Read", "Edit", "Write", "Glob", "Grep", "FileEdit", "Replace"}
    compatible = [{"tool": tc["tool"], "args": tc.get("args", {})} for tc in tool_calls
                  if tc["tool"] in compatible_tools]
    incompatible = [{"tool": tc["tool"], "args": tc.get("args", {}),
                     "result_summary": f"Executed {tc['tool']} operation"}
                    for tc in tool_calls if tc["tool"] not in compatible_tools]

    return {
        "version": "1.0.0",
        "source": {"tool": tool, "model": None},
        "snapshot": {
            "timestamp": now,
            "session_id": session_id,
            "duration_minutes": 0,
            "total_messages": len(conversation),
            "total_tool_calls": len(tool_calls),
        },
        "file_state": {
            "modified": [{"path": p, "diff": git["modified"][0]["diff"] if git["modified"] else None}
                         for p in [m["path"] for m in git["modified"][:50]]],
            "created": git["created"][:20],
            "deleted": git["deleted"][:20],
            "current_branch": git["branch"],
            "uncommitted_count": git["uncommitted"],
        },
        "conversation": conversation[-100:],
        "tool_calls": {"compatible": compatible, "incompatible": incompatible},
        "decisions": decisions[:20],
        "current_intent": intent,
    }


def generate_summary(usf):
    s = usf["source"]
    sn = usf["snapshot"]
    fs = usf["file_state"]
    ci = usf["current_intent"]
    lines = [
        "# ContextFlow Session Summary",
        "",
        f"**Source Tool:** {s['tool']}",
        f"**Session:** {sn['session_id'][:20]}",
        f"**Timestamp:** {sn['timestamp']}",
        f"**Messages:** {sn['total_messages']}",
        f"**Tool Calls:** {sn['total_tool_calls']}",
        "",
    ]
    if fs.get("current_branch"):
        lines.append("## File State")
        lines.append(f"- Branch: `{fs['current_branch']}`")
        lines.append(f"- Uncommitted: {fs['uncommitted_count']}")
        if fs.get("modified"):
            paths = ", ".join(m["path"] for m in fs["modified"][:10])
            lines.append(f"- Modified ({len(fs['modified'])}): {paths}")
        if fs.get("created"):
            paths = ", ".join(c["path"] for c in fs["created"][:5])
            lines.append(f"- Created ({len(fs['created'])}): {paths}")
        lines.append("")
    if usf.get("decisions"):
        lines.append(f"## Decisions ({len(usf['decisions'])})")
        for d in usf["decisions"][:10]:
            lines.append(f"- **{d['topic']}**: chose `{d['chosen']}`")
        lines.append("")
    if ci.get("task"):
        lines.append("## Current Intent")
        lines.append(f"- Task: {ci['task']}")
        if ci.get("completed"):
            lines.append(f"- Completed: {', '.join(ci['completed'][:5])}")
        if ci.get("in_progress"):
            lines.append(f"- In Progress: {', '.join(ci['in_progress'][:5])}")
        if ci.get("next_steps"):
            lines.append(f"- Next Steps: {', '.join(ci['next_steps'][:5])}")
    return "\n".join(lines)


def _row_get(row, key, default=None):
    for k in row.keys():
        if k == key:
            return row[key]
    return default


def _parse_model(raw_model):
    if isinstance(raw_model, str):
        try:
            parsed = json.loads(raw_model)
            if isinstance(parsed, dict):
                return parsed.get("modelID") or parsed.get("id") or raw_model
        except (json.JSONDecodeError, TypeError):
            pass
    return str(raw_model) if raw_model else "unknown"


def extract_open_code(project_dir, session_id=None):
    candidates = [
        _home() / ".local/share/opencode/opencode.db",
        _home() / "AppData/Local/opencode/opencode.db",
    ]
    db_path = None
    for c in candidates:
        if c.exists():
            db_path = c
            break
    if db_path is None:
        return None

    try:
        tmp = Path(tempfile.gettempdir()) / f"opencode-db-{os.getpid()}.db"
        shutil.copy2(str(db_path), str(tmp))
        conn = sqlite3.connect(str(tmp))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        all_sessions = c.execute(
            "SELECT id, title, slug, time_created, model, agent, path FROM session ORDER BY time_created DESC LIMIT 30"
        ).fetchall()
        if not all_sessions:
            conn.close()
            tmp.unlink()
            return None

        sessions = []
        pd_str = str(Path(project_dir)).replace("\\", "/")
        for s in all_sessions:
            spath_raw = _row_get(s, "path")
            try:
                spath = json.loads(spath_raw) if spath_raw else {}
            except (json.JSONDecodeError, TypeError):
                spath = {}
            sdir = (spath.get("root") or spath.get("cwd") or "").replace("\\", "/")
            if sdir and pd_str.startswith(sdir):
                sessions.append(s)
        if not sessions:
            sessions = all_sessions

        target = None
        if session_id:
            for s in sessions:
                if s["id"] == session_id or s["id"].startswith(session_id):
                    target = s
                    break
        if target is None:
            target = sessions[0]

        conversation = []
        msg_rows = c.execute(
            "SELECT time_created, data FROM message WHERE session_id = ? ORDER BY time_created",
            (target["id"],)
        ).fetchall()
        for row in msg_rows:
            try:
                msg_data = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            role = msg_data.get("role", "user")
            content = ""
            for field in ("text", "content", "message"):
                val = msg_data.get(field)
                if val:
                    content += str(val)
            if not content and "summary" in msg_data:
                s = msg_data["summary"]
                if isinstance(s, dict):
                    content = json.dumps(s)[:2000]
            if content:
                conversation.append({"role": role, "content": redact_text(str(content)[:2000])})

        conn.close()
        tmp.unlink()

        raw_model = _parse_model(str(_row_get(target, "model", "unknown")))

        git = get_git_state(project_dir)
        usf = build_usf("opencode", target["id"][:16], conversation, [], git)
        usf["source"]["model"] = raw_model
        return usf
    except Exception:
        return None


def extract_claude_code(project_dir, session_id=None):
    base = _home() / ".claude" / "projects"
    proj_hash = get_project_hash(project_dir)
    session_dir = base / proj_hash
    if not session_dir.exists():
        for d in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir():
                session_dir = d
                break
    if not session_dir.exists():
        return None

    sessions = sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        return None

    target = None
    if session_id:
        for s in sessions:
            if s.stem == session_id or s.stem.startswith(session_id):
                target = s
                break
    if target is None:
        target = sessions[0]

    content = redact_text(target.read_text(errors="replace"))
    conversation = []
    tool_calls = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = entry.get("type", "")
        if etype == "user":
            conversation.append({"role": "user", "content": (entry.get("message") or entry.get("text", ""))[:2000]})
        elif etype == "assistant":
            conversation.append({"role": "assistant", "content": (entry.get("message") or entry.get("text", ""))[:2000]})
        elif etype == "tool_use":
            tool_calls.append({"tool": entry.get("tool", entry.get("name", "unknown")), "args": entry.get("input", {})})

    git = get_git_state(project_dir)
    return build_usf("claude-code", target.stem, conversation, tool_calls, git)


def extract_codex(project_dir, session_id=None):
    base = _home() / ".codex" / "sessions"
    if not base.exists():
        return None
    files = sorted(base.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    target = None
    if session_id:
        for f in files:
            if f.stem == session_id or f.stem.startswith(session_id):
                target = f
                break
    if target is None:
        target = files[0]

    content = redact_text(target.read_text(errors="replace"))
    conversation = []
    tool_calls = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = entry.get("role", "")
        msg = entry.get("message", "") or entry.get("text", "")
        if role == "user":
            conversation.append({"role": "user", "content": msg[:2000]})
        elif role == "assistant":
            conversation.append({"role": "assistant", "content": msg[:2000]})

    git = get_git_state(project_dir)
    return build_usf("codex", target.stem, conversation, tool_calls, git)


def extract_cursor(project_dir, session_id=None):
    base = _home() / ".cursor" / "projects"
    if not base.exists():
        return None
    transcripts = []
    for d in base.iterdir():
        tdir = d / "agent-transcripts"
        if tdir.exists():
            transcripts.extend(tdir.glob("*.txt"))
    transcripts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not transcripts:
        return None

    target = None
    if session_id:
        for t in transcripts:
            if t.stem == session_id or t.stem.startswith(session_id):
                target = t
                break
    if target is None:
        target = transcripts[0]

    content = redact_text(target.read_text(errors="replace"))
    conversation = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("User:") or line.startswith("Human:"):
            conversation.append({"role": "user", "content": line.split(":", 1)[1].strip()[:2000]})
        elif line.startswith("Assistant:") or line.startswith("AI:"):
            conversation.append({"role": "assistant", "content": line.split(":", 1)[1].strip()[:2000]})

    git = get_git_state(project_dir)
    return build_usf("cursor", target.stem, conversation, [], git)


def extract_copilot_cli(project_dir, session_id=None):
    base = _home() / ".copilot" / "session-state"
    if not base.exists():
        return None
    dirs = sorted([d for d in base.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not dirs:
        return None
    target_dir = None
    if session_id:
        for d in dirs:
            if d.name == session_id or d.name.startswith(session_id):
                target_dir = d
                break
    if target_dir is None:
        target_dir = dirs[0]

    events_file = target_dir / "events.jsonl"
    if not events_file.exists():
        return None

    content = redact_text(events_file.read_text(errors="replace"))
    conversation = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = entry.get("type", "")
        data = entry.get("data", {})
        if etype == "user.message":
            conversation.append({"role": "user", "content": str(data.get("message", data.get("text", "")))[:2000]})
        elif etype == "assistant.message":
            conversation.append({"role": "assistant", "content": str(data.get("message", data.get("text", "")))[:2000]})

    git = get_git_state(project_dir)
    return build_usf("copilot-cli", target_dir.name, conversation, [], git)


EXTRACTORS = {
    "OPENCODE": extract_open_code,
    "CLAUDECODE": extract_claude_code,
    "CURSOR": extract_cursor,
    "CODEX": extract_codex,
    "COPILOT_CLI": extract_copilot_cli,
}


def _cleanup_old_snapshots(bridge_dir, max_days=RETENTION_DAYS):
    bridge = Path(bridge_dir)
    if not bridge.exists():
        return
    now = datetime.now().timestamp()
    cutoff = now - (max_days * 86400)
    removed = 0
    for entry in bridge.iterdir():
        if entry.is_dir() and (entry / "session.usf.json").exists():
            mtime = entry.stat().st_mtime
            if mtime < cutoff:
                shutil.rmtree(str(entry), ignore_errors=True)
                removed += 1
    if removed:
        print(f"  Cleaned up {removed} snapshot(s) older than {max_days} days")


def main():
    parser = argparse.ArgumentParser(description="Save session context (no LLM required)")
    parser.add_argument("--label", "-l", default=None, help="Snapshot label")
    parser.add_argument("--session-id", default=None, help="Specific session ID")
    parser.add_argument("--tool", default=None, help="Force tool type")
    parser.add_argument("--project-dir", default=None, help="Project directory")
    parser.add_argument("--global", dest="use_global", action="store_true", help="Store to ~/.session-bridge/")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip 30-day retention cleanup")
    args = parser.parse_args()

    project_dir = Path(args.project_dir or Path.cwd()).resolve()

    tool_id = args.tool or detect_tool(project_dir)
    if not tool_id:
        print("Error: Could not detect tool. Run from a project directory.", file=sys.stderr)
        sys.exit(1)

    tool_name = TOOL_NAMES.get(tool_id, tool_id)
    extractor = EXTRACTORS.get(tool_id)
    if not extractor:
        print(f"Error: No extractor for {tool_name}", file=sys.stderr)
        sys.exit(1)

    usf = extractor(str(project_dir), args.session_id)
    if usf is None:
        print(f"Error: No session data found for {tool_name}", file=sys.stderr)
        sys.exit(1)

    snapshot_parts = [tool_name]
    if args.label:
        safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", args.label)[:32]
        snapshot_parts.append(safe_label)
    snapshot_parts.append(usf["snapshot"]["session_id"][:32])
    snapshot_name = "-".join(snapshot_parts)

    if args.use_global:
        proj_hash = get_project_hash(project_dir)
        bridge_dir = _home() / ".session-bridge" / proj_hash
    else:
        bridge_dir = project_dir / ".session-bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)

    snapshot_dir = bridge_dir / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    usf_path = snapshot_dir / "session.usf.json"
    usf_path.write_text(json.dumps(usf, indent=2, default=str), encoding="utf-8")

    summary = generate_summary(usf)
    summary_path = snapshot_dir / "session.summary.md"
    summary_path.write_text(summary, encoding="utf-8")

    print(f"Saved to: {snapshot_dir}/")
    print(f"  session.usf.json  ({os.path.getsize(str(usf_path))} bytes)")
    print(f"  session.summary.md ({len(summary)} chars)")
    print(f"  Tool: {tool_name}")
    print(f"  Session: {usf['snapshot']['session_id'][:20]}")
    print(f"  Messages: {usf['snapshot']['total_messages']}")
    print(f"  Decisions: {len(usf.get('decisions', []))}")
    if usf["current_intent"]["task"]:
        print(f"  Task: {usf['current_intent']['task'][:80]}")

    if not args.no_cleanup:
        _cleanup_old_snapshots(bridge_dir)


if __name__ == "__main__":
    main()
