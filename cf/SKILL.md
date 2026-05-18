---
name: cf
description: >
  Save and load AI coding session context across tools (Claude Code, Codex, Cursor, OpenCode, Copilot CLI).
  Use this skill when the user says "/cf save", "/cf load", or "/cf status", or when switching tools
  due to rate limits, cost optimization, or model capability gaps.
  Do NOT auto-trigger on general development questions.
license: MIT
compatibility: >
  Requires Bash to run Python scripts in cf/scripts/. Requires Read, Glob, Grep to discover
  session files on disk. Works on Linux, macOS, and Windows.
allowed-tools: Bash, Read, Glob, Grep, Edit, Write
metadata:
  audience: developers
  workflow: session-migration
---

# ContextFlow — /cf

Save and load session context across AI coding tools. Provides five slash commands:

- `/cf save` — persist current session to `.session-bridge/`
- `/cf load <id>` — restore a saved session's context
- `/cf status` — list saved snapshots
- `/cf diff <id1> [<id2>]` — compare two snapshots
- `/cf validate <id>` — validate a snapshot against the USF schema

## Save (No LLM)

User says `/cf save`. Execute `cf/scripts/cf-save.py` with Bash.

**Script steps:**
1. Detect the current tool from project-level config files or session storage paths
2. Read session files from disk (JSONL / SQLite / TXT) — tool-specific locations
3. Extract five layers: file state, conversation, tool calls, decisions, current intent
4. Write to `.session-bridge/<tool>-<session-id>/`:
   - `session.usf.json` — full structured data (Universal Session Format)
   - `session.summary.md` — plain-text overview

After the script finishes, read `session.summary.md` and relay the key info to the user.

**No LLM used.** Works during rate limits. User can also run directly:
```bash
python3 cf/scripts/cf-save.py
```
Windows: `py cf\scripts\cf-save.py`

**Flags:** `--label`, `--session-id`, `--tool`, `--project-dir`, `--global`, `--no-cleanup`

## Load (LLM Required)

User says `/cf load <snapshot-id>` (or `/cf load latest`).

**Steps:**
1. Read `session.usf.json` from `.session-bridge/<snapshot-id>/`
2. Read `session.summary.md` for quick orientation
3. Analyze the USF with the LLM:
   - Reclassify each tool call as compatible or incompatible with the current tool
   - Summarize completed work from decisions and intent layers
   - Identify in-progress tasks, blockers, next steps
4. Present findings and continue the work seamlessly

**Compatible tools:** Bash, Read, Edit, Write, Glob, Grep, FileEdit, Replace — available in every tool. Pass through unchanged.

**Incompatible tools:** ClaudeCode, Skill, Terminal, Message — tool-specific. Translate each into a human-readable summary of what it accomplished. The effects are visible in file state.

## Status (No LLM)

User says `/cf status`. Execute `cf/scripts/cf-status.py` with Bash.

Lists all snapshots in `.session-bridge/` with size, age, tool, and message count.

## Diff (No LLM)

User says `/cf diff <id1> [<id2>]`. If `<id2>` omitted, compare against latest. Execute `cf/scripts/cf-diff.py` with Bash.

Compares two snapshots at the field level: source metadata, file state, conversation length, decisions, intent. Outputs a structured diff with before/after values.

## Validate (No LLM)

User says `/cf validate <id>`. Execute `cf/scripts/cf-validate.py` with Bash.

Validates a snapshot's `session.usf.json` against the required USF schema fields. Reports missing fields, type mismatches, and warnings for non-standard tool names.

## Retention

Save script automatically removes snapshots older than 30 days. User can pass `--no-cleanup` to skip removal.

## Universal Session Format

The USF JSON shape:

```jsonc
{
  "version": "1.0.0",
  "source": { "tool": "claude-code", "model": "claude-sonnet-4-20250514" },
  "snapshot": {
    "timestamp": "2026-05-18T10:00:00Z",
    "session_id": "abc123-def456",
    "duration_minutes": 287,
    "total_messages": 42,
    "total_tool_calls": 156
  },
  "file_state": {
    "modified": [{ "path": "src/auth.ts", "diff": "@@ -10,5 +10,8 @@..." }],
    "created": [{ "path": "src/middleware.ts" }],
    "deleted": ["src/legacy.ts"],
    "current_branch": "feature/auth",
    "uncommitted_count": 3
  },
  "conversation": [
    { "role": "user", "content": "Implement JWT auth..." },
    { "role": "assistant", "content": "I will do it in three steps..." }
  ],
  "tool_calls": {
    "compatible": [ { "tool": "Read", "args": { "file_path": "src/auth.ts" } } ],
    "incompatible": [ { "tool": "ClaudeCode", "args": {}, "result_summary": "Analyzed code structure" } ]
  },
  "decisions": [
    {
      "topic": "Authentication scheme",
      "chosen": "JWT + refresh tokens",
      "rejected": ["session-based", "OAuth-only"],
      "reasoning": "Stateless, works with microservices architecture"
    }
  ],
  "current_intent": {
    "task": "Implement JWT authentication",
    "completed": ["token generation", "verification middleware"],
    "in_progress": ["refresh token logic"],
    "next_steps": ["implement refresh endpoint", "add token expiry"],
    "blockers": ["need to confirm Redis integration"],
    "confidence": 0.85
  }
}
```

Schema at `cf/schemas/usf-schema.json`. Detailed USF field guide at `cf/references/usf-guide.md`.

Session source details per tool at `cf/references/tool-sessions.md` — read when the save script fails or when debugging extraction for a specific tool.

## Privacy

The save script redacts:
- API keys, tokens, passwords, private keys (regex pattern matching)
- Common secret file patterns (`*.pem`, `*.key`)
- Sensitive environment variable values
- Long alphanumeric strings matching credential patterns

## Installation

Place `cf/` as a symlink or copy into the tool's skills directory.

### OpenCode
```bash
# Unix
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf

# Windows (Admin PowerShell)
New-Item -ItemType Junction -Path "$env:USERPROFILE\.config\opencode\skills\cf" -Target "$pwd\cf"
```

### Claude Code
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

### Any tool
Copy the `cf/` directory into the tool's configured skills path.

## Examples

**Rate-limit switch:**
User hits a rate limit in Claude Code and types `/cf save`.
Script saves to `.session-bridge/claude-code-abc123/`.
User opens Codex, types `/cf load latest`.
Load reads USF and continues the implementation task without re-explaining context.

**Cost optimization:**
User finishes design review in Claude Opus, does `/cf save --label design-review`, switches to GPT-4o-mini, does `/cf load design-review`. Load task is to understand the decisions and implement without re-explaining.

**Same-tool model switch:**
User does `/cf save`, switches model in the same tool, does `/cf load latest`. Load task is to identify incompatible tool calls from the previous model and continue.
