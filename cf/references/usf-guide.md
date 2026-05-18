# USF Field Reference

The Universal Session Format (USF) captures five layers of development context.

## version

**Type:** string (semver)  
**Current value:** `1.0.0`

Schema version for forward/backward compatibility.

## source

Identifies the origin tool and model.

```jsonc
{ "tool": "opencode", "model": "deepseek-v4-flash-free" }
```

- `tool` — one of: `opencode`, `claude-code`, `codex`, `cursor`, `copilot-cli`
- `model` — the model name/ID used during the session. May be a JSON string if stored by the tool

## snapshot

Session-level metadata.

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 UTC save time |
| `session_id` | Tool-specific session identifier |
| `duration_minutes` | Session duration (may be 0 if not tracked) |
| `total_messages` | Number of conversation messages extracted |
| `total_tool_calls` | Number of tool calls extracted |

## file_state

Current project state from git.

| Field | Description |
|-------|-------------|
| `modified` | Files with unstaged changes + truncated diff |
| `created` | New untracked files |
| `deleted` | Deleted files |
| `current_branch` | Active git branch |
| `uncommitted_count` | Count of uncommitted changes |

The `diff` field in each modified entry is truncated to 2000 characters to keep the USF manageable.

## conversation

Array of `{ role, content }` pairs. Roles are `user`, `assistant`, `system`, or `tool`.

**Content availability varies by tool:**
- **Claude Code / Codex / Cursor / Copilot CLI** — Full conversation text is available
- **OpenCode** — Only assistant summary diffs are persisted; user text is not available

The save script limits conversation to the last 100 messages and truncates each message to 2000 characters.

## tool_calls

Classified into compatible and incompatible:

**Compatible** — tools available in every coding agent:
- `Bash`, `Read`, `Edit`, `Write`, `Glob`, `Grep`, `FileEdit`, `Replace`

**Incompatible** — tool-specific tools that need human-readable summaries:
- `ClaudeCode`, `Skill`, `Terminal`, `Message`, and any other tool not in the compatible list

Each call includes `{ tool, args, result_summary }`. The `args` field captures the raw input parameters; `result_summary` is a brief description of what was accomplished.

## decisions

Extracted from conversation text by regex pattern matching for phrases like:
- "I decided to..."
- "I chose..."
- "I selected..."
- "I went with..."
- "I abandoned..."
- "I rejected..."

Each decision has:
- `topic` — extracted phrase (80 char max)
- `chosen` — what was selected
- `rejected` — alternatives that were considered and rejected
- `reasoning` — explanation of why (may be empty if not found in text)

This is a heuristic extraction. The load agent should verify and enrich decisions.

## current_intent

The inferred current task state:

| Field | Description |
|-------|-------------|
| `task` | Last user message (200 char max) |
| `completed` | Modified files from git state |
| `in_progress` | Last user message excerpt |
| `next_steps` | Empty by default, to be filled by load agent |
| `blockers` | Empty by default, to be filled by load agent |
| `confidence` | Always 0.5 — heuristic placeholder |

The load agent should analyze the full USF and update `next_steps`, `blockers`, and `confidence` based on LLM understanding.

## Privacy

The save script applies these redactions before writing:
- `api_key`, `secret`, `token`, `password`, `private_key` assignment patterns
- `sk-...` OpenAI-style keys (40+ chars)
- Arbitrary 40+ character alphanumeric strings
- Private key headers (`-----BEGIN PRIVATE KEY-----`)
- `.env` file contents (handled by git state exclusion)

Redaction is applied per-line before JSON serialization.
