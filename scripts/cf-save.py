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

# Truncation limits — keep USF manageable for context windows
MAX_MESSAGE_CHARS = 2000       # Single message content length
MAX_SNAPSHOT_ID = 32           # Snapshot directory name segment
MAX_SAFE_LABEL = 32            # User-provided label length
MAX_MODIFIED_FILES = 50        # Files listed in file_state.modified
MAX_CREATED_FILES = 20         # Files listed in file_state.created
MAX_DELETED_FILES = 20         # Files listed in file_state.deleted
MAX_DECISIONS = 20             # Decision entries extracted
MAX_CONVERSATION = 100         # Recent messages kept
MAX_DIFF_CHARS = 2000          # Diff content per modified file
MAX_INTENT_TASK = 200          # Current intent task description
MAX_INTENT_EXCERPT = 100       # In-progress intent excerpt
MAX_TOPIC_CHARS = 80           # Decision topic text
MAX_SUMMARY_MSGS = 10          # Messages used for summary generation
MAX_DECISION_PATTERNS = 10     # Decisions shown in summary
MAX_SUMMARY_FILES = 10         # Modified files shown in summary
MAX_SUMMARY_CREATED = 5        # Created files shown in summary
MAX_INTENT_COMPLETED = 5       # Completed items in current_intent
MAX_SUMMARY_INTENT = 5         # Intent items shown in summary
MAX_SESSION_DISPLAY = 20       # Session ID chars in summary/print output
MAX_OPENCODE_SESSION_ID = 16   # OpenCode session ID segment length


TOOL_NAMES = {
    "OPENCODE": "opencode",
    "CLAUDECODE": "claude-code",
    "CURSOR": "cursor",
    "CODEX": "codex",
    "COPILOT_CLI": "copilot-cli",
    "GEMINI_CLI": "gemini-cli",
}

# Map from cf-detect agent names to internal tool IDs
AGENT_NAME_TO_ID = {
    "Claude Code": "CLAUDECODE",
    "Codex": "CODEX",
    "OpenCode": "OPENCODE",
    "GitHub Copilot CLI": "COPILOT_CLI",
    "Gemini CLI": "GEMINI_CLI",
    "Cursor": "CURSOR",
}


SENSITIVE_PATTERNS = [
    # Key/secret assignment patterns: api_key=..., token: "...", password ...
    re.compile(r"(?i)(api[_-]?key|secret|token|password|private[_-]?key|passwd|bearer|credentials?)[=:]\s*['\"]?[A-Za-z0-9_\-+/=]{8,}['\"]?"),
    # OpenAI-style keys
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    # GitHub tokens (ghp_, gho_, ghs_, ghu_, github_pat_)
    re.compile(r"\b(gh[opsu]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    # AWS access keys
    re.compile(r"\b(AKIA[A-Z0-9]{16})\b"),
    # JWT tokens (two base64 segments separated by dot)
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}"),
    # PEM private key headers
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
                           cwd=str(project_dir), timeout=5, encoding="utf-8", errors="replace")
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
                modified.append({"path": parts[0].strip(), "diff": (diff_full or "")[:MAX_DIFF_CHARS]})

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
        "modified": modified[:MAX_MODIFIED_FILES],
        "created": created[:MAX_CREATED_FILES],
        "deleted": deleted[:MAX_DELETED_FILES],
    }


def get_project_hash(project_dir):
    """Compute project hash for session directory lookup.

    Claude Code uses path-based encoding (not SHA256): colons, slashes,
    and backslashes are replaced with dashes. We check both the encoded
    name and SHA256 prefix to support future changes.
    """
    pd_str = str(project_dir)
    encoded = pd_str.replace(":", "-").replace("/", "-").replace("\\", "-")
    return encoded


def _find_claude_session_dir(project_dir):
    """Find Claude Code's session directory for a project."""
    base = _home() / ".claude" / "projects"
    if not base.exists():
        return None
    encoded = get_project_hash(project_dir)
    # Try exact encoded name first
    candidate = base / encoded
    if candidate.exists():
        return candidate
    # Fallback: match by partial name (in case of slight encoding differences)
    for d in base.iterdir():
        if d.is_dir() and encoded.lower() in d.name.lower():
            return d
    return None


_cf_detect_module = None


def _get_cf_detect():
    global _cf_detect_module
    if _cf_detect_module is None:
        script_dir = Path(__file__).resolve().parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        import importlib
        _cf_detect_module = importlib.import_module("cf-detect")
    return _cf_detect_module


def detect_tool(project_dir):
    """Detect the current tool using cf-detect (env vars + process tree).

    Returns an internal tool ID (e.g. "CLAUDECODE") or None.
    """
    cf_detect = _get_cf_detect()
    result = cf_detect.detect_agent_context(refresh=True)

    # Phase 1: immediate_agent from cf-detect (env vars + process tree)
    agent = result.immediate_agent or result.root_agent
    if agent:
        tool_id = AGENT_NAME_TO_ID.get(agent)
        if tool_id:
            print(f"  Detected: {agent} (confidence: {result.confidence})", file=sys.stderr)
            return tool_id

    # Phase 2: terminal_host — e.g. running inside Cursor's terminal
    if result.terminal_host:
        tool_id = AGENT_NAME_TO_ID.get(result.terminal_host)
        if tool_id:
            print(f"  Detected terminal: {result.terminal_host}", file=sys.stderr)
            return tool_id

    # Phase 3: most recently active session file (last resort)
    best_tool = None
    best_mtime = 0

    claude_dir = _find_claude_session_dir(Path(project_dir))
    if claude_dir:
        for f in claude_dir.glob("*.jsonl"):
            mtime = f.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_tool = "CLAUDECODE"

    codex_dir = Path.home() / ".codex" / "sessions"
    if codex_dir.exists():
        for f in codex_dir.rglob("rollout-*.jsonl"):
            mtime = f.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_tool = "CODEX"

    for db_candidate in [Path.home() / ".local/share/opencode/opencode.db",
                          Path.home() / "AppData/Local/opencode/opencode.db"]:
        if db_candidate.exists():
            mtime = db_candidate.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_tool = "OPENCODE"
            break

    cursor_dir = Path.home() / ".cursor" / "projects"
    if cursor_dir.exists():
        for d in cursor_dir.iterdir():
            tdir = d / "agent-transcripts"
            if tdir.exists():
                for f in tdir.glob("*.txt"):
                    mtime = f.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_tool = "CURSOR"

    copilot_dir = Path.home() / ".copilot" / "session-state"
    if copilot_dir.exists():
        for d in copilot_dir.iterdir():
            if d.is_dir():
                ws = d / "workspace.yaml"
                if ws.exists():
                    mtime = ws.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_tool = "COPILOT_CLI"

    # Gemini CLI: check session files
    gemini_projects = Path.home() / ".gemini" / "projects.json"
    if gemini_projects.exists():
        try:
            proj_map = json.loads(gemini_projects.read_text(encoding="utf-8")).get("projects", {})
            pd_str = str(Path(project_dir).resolve()).replace("\\", "/").lower()
            for proj_dir, slug in proj_map.items():
                if proj_dir.replace("\\", "/").lower() == pd_str:
                    chat_dir = Path.home() / ".gemini" / "tmp" / slug / "chats"
                    if chat_dir.exists():
                        for f in chat_dir.glob("session-*.json"):
                            mtime = f.stat().st_mtime
                            if mtime > best_mtime:
                                best_mtime = mtime
                                best_tool = "GEMINI_CLI"
                    break
        except (json.JSONDecodeError, OSError):
            pass

    if best_tool:
        print(f"  Detected via session mtime: {best_tool}", file=sys.stderr)
    return best_tool


def build_usf(tool, session_id, conversation, tool_calls, git):
    now = datetime.now(timezone.utc).isoformat()
    conv_text = " ".join(c["content"] for c in conversation[-MAX_SUMMARY_MSGS:])

    decisions = []
    kw_patterns = [r"(?:I\s+(?:decided|chose|selected|picked|went with|abandoned|rejected|preferred)\s+[^.!?]+)"]
    for pat in kw_patterns:
        for m in re.finditer(pat, conv_text, re.IGNORECASE):
            topic = m.group()[:MAX_TOPIC_CHARS]
            decisions.append({"topic": topic, "chosen": m.group()[:MAX_TOPIC_CHARS], "rejected": [], "reasoning": ""})

    last_msgs = [c["content"] for c in conversation[-4:] if c["role"] == "user"]
    intent = {
        "task": last_msgs[-1][:MAX_INTENT_TASK] if last_msgs else None,
        "completed": [m["path"] for m in (git["modified"] or [])[:MAX_INTENT_COMPLETED]],
        "in_progress": [last_msgs[-1][:MAX_INTENT_EXCERPT]] if last_msgs else [],
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
                         for p in [m["path"] for m in git["modified"][:MAX_MODIFIED_FILES]]],
            "created": git["created"][:MAX_CREATED_FILES],
            "deleted": git["deleted"][:MAX_DELETED_FILES],
            "current_branch": git["branch"],
            "uncommitted_count": git["uncommitted"],
        },
        "conversation": conversation[-MAX_CONVERSATION:],
        "tool_calls": {"compatible": compatible, "incompatible": incompatible},
        "decisions": decisions[:MAX_DECISIONS],
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
        f"**Session:** {sn['session_id'][:MAX_SESSION_DISPLAY]}",
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
            paths = ", ".join(m["path"] for m in fs["modified"][:MAX_SUMMARY_FILES])
            lines.append(f"- Modified ({len(fs['modified'])}): {paths}")
        if fs.get("created"):
            paths = ", ".join(c["path"] for c in fs["created"][:MAX_SUMMARY_CREATED])
            lines.append(f"- Created ({len(fs['created'])}): {paths}")
        lines.append("")
    if usf.get("decisions"):
        lines.append(f"## Decisions ({len(usf['decisions'])})")
        for d in usf["decisions"][:MAX_DECISION_PATTERNS]:
            lines.append(f"- **{d['topic']}**: chose `{d['chosen']}`")
        lines.append("")
    if ci.get("task"):
        lines.append("## Current Intent")
        lines.append(f"- Task: {ci['task']}")
        if ci.get("completed"):
            lines.append(f"- Completed: {', '.join(ci['completed'][:MAX_SUMMARY_INTENT])}")
        if ci.get("in_progress"):
            lines.append(f"- In Progress: {', '.join(ci['in_progress'][:MAX_SUMMARY_INTENT])}")
        if ci.get("next_steps"):
            lines.append(f"- Next Steps: {', '.join(ci['next_steps'][:MAX_SUMMARY_INTENT])}")
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
        print("  OpenCode DB not found — is OpenCode installed?", file=sys.stderr)
        return None

    try:
        tmp = Path(tempfile.gettempdir()) / f"opencode-db-{os.getpid()}.db"
        source_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn = sqlite3.connect(str(tmp))
        source_conn.backup(conn)
        source_conn.close()
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
        tool_calls = []
        msg_rows = c.execute(
            "SELECT id, data FROM message WHERE session_id = ? ORDER BY time_created",
            (target["id"],)
        ).fetchall()
        for row in msg_rows:
            try:
                msg_data = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            role = msg_data.get("role", "user")
            msg_id = row["id"]

            # OpenCode stores actual content in the `part` table, not in message.data
            parts = c.execute(
                "SELECT data FROM part WHERE message_id = ? ORDER BY time_created",
                (msg_id,)
            ).fetchall()
            text_parts = []
            for part_row in parts:
                try:
                    pdata = json.loads(part_row["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                ptype = pdata.get("type", "")
                if ptype in ("text", "reasoning"):
                    t = pdata.get("text", "")
                    if t:
                        text_parts.append(t)
                elif ptype == "tool":
                    state = pdata.get("state", {})
                    tool_name = pdata.get("tool", "unknown")
                    tool_input = state.get("input", {})
                    tool_output = state.get("output", "")
                    if isinstance(tool_input, dict):
                        tool_calls.append({"tool": tool_name, "args": tool_input})
                    # Also capture tool output as context
                    if tool_output:
                        text_parts.append(f"[{tool_name}] {tool_output}")

            if text_parts:
                combined = "\n".join(text_parts)
                conversation.append({"role": role, "content": redact_text(combined[:MAX_MESSAGE_CHARS])})

        conn.close()
        tmp.unlink()

        raw_model = _parse_model(str(_row_get(target, "model", "unknown")))

        git = get_git_state(project_dir)
        usf = build_usf("opencode", target["id"][:MAX_OPENCODE_SESSION_ID], conversation, tool_calls, git)
        usf["source"]["model"] = raw_model
        return usf
    except sqlite3.OperationalError as e:
        print(f"  OpenCode DB read error: {e}", file=sys.stderr)
        return None
    except PermissionError:
        print(f"  OpenCode DB permission denied: {db_path}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  OpenCode extraction failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def extract_claude_code(project_dir, session_id=None):
    base = _home() / ".claude" / "projects"
    if not base.exists():
        print("  Claude Code sessions directory not found", file=sys.stderr)
        return None
    session_dir = _find_claude_session_dir(project_dir)
    if session_dir is None:
        # Fallback: most recently modified project directory
        for d in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir():
                session_dir = d
                break
    if session_dir is None or not session_dir.exists():
        print(f"  No Claude Code session directory for this project", file=sys.stderr)
        return None

    sessions = sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        print(f"  No JSONL sessions found in {session_dir}", file=sys.stderr)
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

        # Extract text from message field (may be dict with 'content' key, or string)
        raw_msg = entry.get("message", entry.get("text", ""))
        if isinstance(raw_msg, dict):
            msg_text = raw_msg.get("content", "")
            if isinstance(msg_text, list):
                # Content blocks: extract text from each
                parts = []
                for block in msg_text:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                msg_text = "\n".join(parts)
            msg_text = str(msg_text)
        else:
            msg_text = str(raw_msg) if raw_msg else ""

        if etype == "user" and msg_text:
            conversation.append({"role": "user", "content": msg_text[:MAX_MESSAGE_CHARS]})
        elif etype == "assistant" and msg_text:
            conversation.append({"role": "assistant", "content": msg_text[:MAX_MESSAGE_CHARS]})
        elif etype == "tool_use":
            tool_calls.append({"tool": entry.get("tool", entry.get("name", "unknown")), "args": entry.get("input", {})})

    git = get_git_state(project_dir)
    return build_usf("claude-code", target.stem, conversation, tool_calls, git)


def extract_codex(project_dir, session_id=None):
    base = _home() / ".codex" / "sessions"
    if not base.exists():
        print("  Codex sessions directory not found — is Codex installed?", file=sys.stderr)
        return None
    files = sorted(base.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print(f"  No rollout JSONL files found in {base}", file=sys.stderr)
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
            conversation.append({"role": "user", "content": msg[:MAX_MESSAGE_CHARS]})
        elif role == "assistant":
            conversation.append({"role": "assistant", "content": msg[:MAX_MESSAGE_CHARS]})

    git = get_git_state(project_dir)
    return build_usf("codex", target.stem, conversation, tool_calls, git)


def extract_cursor(project_dir, session_id=None):
    base = _home() / ".cursor" / "projects"
    if not base.exists():
        print("  Cursor projects directory not found — is Cursor installed?", file=sys.stderr)
        return None
    transcripts = []
    for d in base.iterdir():
        tdir = d / "agent-transcripts"
        if tdir.exists():
            transcripts.extend(tdir.glob("*.txt"))
    transcripts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not transcripts:
        print(f"  No agent transcripts found in {base}", file=sys.stderr)
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
            conversation.append({"role": "user", "content": line.split(":", 1)[1].strip()[:MAX_MESSAGE_CHARS]})
        elif line.startswith("Assistant:") or line.startswith("AI:"):
            conversation.append({"role": "assistant", "content": line.split(":", 1)[1].strip()[:MAX_MESSAGE_CHARS]})

    git = get_git_state(project_dir)
    return build_usf("cursor", target.stem, conversation, [], git)


def extract_copilot_cli(project_dir, session_id=None):
    base = _home() / ".copilot" / "session-state"
    if not base.exists():
        print("  Copilot CLI session-state not found — is Copilot CLI installed?", file=sys.stderr)
        return None
    dirs = sorted([d for d in base.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not dirs:
        print(f"  No session directories found in {base}", file=sys.stderr)
        return None
    target_dir = None
    if session_id:
        for d in dirs:
            if d.name == session_id or d.name.startswith(session_id):
                target_dir = d
                break
    if target_dir is None:
        target_dir = dirs[0]

    # Read workspace.yaml for session metadata
    workspace_file = target_dir / "workspace.yaml"
    ws_id = target_dir.name
    if workspace_file.exists():
        try:
            import yaml
            ws_data = yaml.safe_load(workspace_file.read_text(encoding="utf-8"))
            ws_id = ws_data.get("id", ws_id)
        except ImportError:
            # No PyYAML — parse manually for simple key: value format
            for line in workspace_file.read_text(encoding="utf-8").split("\n"):
                if line.startswith("id:"):
                    ws_id = line.split(":", 1)[1].strip()
                    break
        except Exception as e:
            print(f"  Warning: could not parse workspace.yaml: {e}", file=sys.stderr)

    # Copilot CLI (v1.0+) stores workspace metadata + checkpoints,
    # but does not persist conversation content.
    print("  Note: Copilot CLI does not persist conversation text — metadata only", file=sys.stderr)

    # Try reading checkpoints for context
    conversation = []
    checkpoints_file = target_dir / "checkpoints" / "index.md"
    if checkpoints_file.exists():
        cp_content = checkpoints_file.read_text(encoding="utf-8", errors="replace")
        if cp_content.strip():
            conversation.append({"role": "system", "content": redact_text(cp_content[:MAX_MESSAGE_CHARS])})

    git = get_git_state(project_dir)
    return build_usf("copilot-cli", ws_id, conversation, [], git)


def _find_gemini_project_slug(project_dir):
    """Look up project slug from ~/.gemini/projects.json."""
    projects_file = _home() / ".gemini" / "projects.json"
    if not projects_file.exists():
        return None
    try:
        data = json.loads(projects_file.read_text(encoding="utf-8"))
        proj_map = data.get("projects", {})
        pd_str = str(Path(project_dir).resolve()).replace("\\", "/").lower()
        for proj_dir, slug in proj_map.items():
            if proj_dir.replace("\\", "/").lower() == pd_str:
                return slug
    except (json.JSONDecodeError, OSError):
        pass
    return None


def extract_gemini_cli(project_dir, session_id=None):
    # Find project slug
    slug = _find_gemini_project_slug(project_dir)
    if not slug:
        # Fallback: try all project directories
        tmp_dir = _home() / ".gemini" / "tmp"
        if not tmp_dir.exists():
            print("  Gemini CLI data not found — is Gemini CLI installed?", file=sys.stderr)
            return None
        # Use the most recently modified project directory
        candidates = sorted(
            [d for d in tmp_dir.iterdir() if d.is_dir()],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        slug = candidates[0].name if candidates else None
        if not slug:
            print("  No Gemini CLI project directories found", file=sys.stderr)
            return None

    chat_dir = _home() / ".gemini" / "tmp" / slug / "chats"
    if not chat_dir.exists():
        print(f"  No Gemini CLI chats directory for project '{slug}'", file=sys.stderr)
        return None

    sessions = sorted(chat_dir.glob("session-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        print(f"  No Gemini CLI session files found in {chat_dir}", file=sys.stderr)
        return None

    target = None
    if session_id:
        for s in sessions:
            if session_id in s.stem:
                target = s
                break
    if target is None:
        target = sessions[0]

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Gemini CLI session read error: {e}", file=sys.stderr)
        return None

    conversation = []
    tool_calls = []
    session_id_val = raw.get("sessionId", target.stem)

    for msg in raw.get("messages", []):
        msg_type = msg.get("type", "")
        content = msg.get("content", "")
        if not content:
            continue

        role = "system"
        if msg_type == "user":
            role = "user"
        elif msg_type in ("assistant", "model"):
            role = "assistant"
        elif msg_type == "tool":
            tool_name = msg.get("tool_name", "unknown")
            tool_input = msg.get("tool_input", {})
            tool_calls.append({"tool": tool_name, "args": tool_input})
            continue
        elif msg_type not in ("info",):
            # Unknown type — treat as system
            pass

        conversation.append({"role": role, "content": redact_text(content[:MAX_MESSAGE_CHARS])})

    git = get_git_state(project_dir)
    return build_usf("gemini-cli", session_id_val, conversation, tool_calls, git)


EXTRACTORS = {
    "OPENCODE": extract_open_code,
    "CLAUDECODE": extract_claude_code,
    "CURSOR": extract_cursor,
    "CODEX": extract_codex,
    "COPILOT_CLI": extract_copilot_cli,
    "GEMINI_CLI": extract_gemini_cli,
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


def _ensure_gitignore(project_dir, bridge_dir):
    """Add .session-bridge/ to .gitignore if saving locally inside a git repo."""
    if str(bridge_dir).startswith(str(_home())):
        return
    gitignore = project_dir / ".gitignore"
    ignore_entry = ".session-bridge/"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if re.search(r"^\.session-bridge/", content, re.MULTILINE):
            return
        content = content.rstrip("\n") + "\n" + ignore_entry + "\n"
        gitignore.write_text(content, encoding="utf-8")
        print(f"  Added '{ignore_entry}' to .gitignore")
    else:
        gitignore.write_text(ignore_entry + "\n", encoding="utf-8")
        print(f"  Created .gitignore with '{ignore_entry}'")


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

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

    # Normalize: accept both "claude-code" and "CLAUDECODE" via reverse lookup
    TOOL_NAME_TO_ID = {v: k for k, v in TOOL_NAMES.items()}
    if tool_id in TOOL_NAME_TO_ID:
        tool_id = TOOL_NAME_TO_ID[tool_id]

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
        safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", args.label)[:MAX_SAFE_LABEL]
        snapshot_parts.append(safe_label)
    snapshot_parts.append(usf["snapshot"]["session_id"][:MAX_SNAPSHOT_ID])
    snapshot_name = "-".join(snapshot_parts)

    if args.use_global:
        proj_hash = get_project_hash(project_dir)
        bridge_dir = _home() / ".session-bridge" / proj_hash
    else:
        bridge_dir = project_dir / ".session-bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(project_dir, bridge_dir)

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
    print(f"  Session: {usf['snapshot']['session_id'][:MAX_SESSION_DISPLAY]}")
    print(f"  Messages: {usf['snapshot']['total_messages']}")
    print(f"  Decisions: {len(usf.get('decisions', []))}")
    if usf["current_intent"]["task"]:
        print(f"  Task: {usf['current_intent']['task'][:MAX_TOPIC_CHARS]}")

    if not args.no_cleanup:
        _cleanup_old_snapshots(bridge_dir)


if __name__ == "__main__":
    main()
