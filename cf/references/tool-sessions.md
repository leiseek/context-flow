# Tool Session Sources

Detailed session file locations and extraction notes for each supported tool.

## OpenCode

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.local/share/opencode/opencode.db` |
| **Windows path** | `%LOCALAPPDATA%\opencode\opencode.db` |
| **Format** | SQLite |
| **Tables used** | `session`, `message` |
| **Schema notes** | `session.time_created` is unix ms timestamp. `message.data` is a JSON blob with keys `role`, `agent`, `model`, `summary.diffs`. User text content is not persisted — only assistant summary diffs are available. |

**Extraction:**
- The DB is copied to a temp file before querying to avoid locking
- Sessions are matched to the current project via the `path` JSON column (`root`/`cwd`)
- Conversation is reconstructed from `message.data` by extracting `text`, `content`, `message` fields and falling back to `summary` JSON

**Limitations:** Full user/assistant conversation text is NOT persisted by OpenCode. Only file diffs and session metadata are available.

## Claude Code

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.claude/projects/<project-hash>/` |
| **Windows path** | `%USERPROFILE%\.claude\projects\<hash>\` |
| **Format** | JSONL (one JSON object per line) |
| **Line types** | `user`, `assistant`, `tool_use` |

**Extraction:**
- The project hash is SHA256(project-dir) first 32 chars
- Sessions are `.jsonl` files sorted by mtime
- Each JSON line has `type` (`user`/`assistant`/`tool_use`), `message`/`text` content, and `tool`/`name` + `input` for tool calls

**Limitations:** None — full conversation text is available.

## Codex

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |
| **Windows path** | `%USERPROFILE%\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl` |
| **Format** | JSONL |
| **Line keys** | `role`, `message`, `text` |

**Extraction:**
- Files are globbed recursively by date directory
- Entries have `role` (`user`/`assistant`) and `message` or `text` content

**Limitations:** Tool call information may not be captured as structured data — only conversation messages.

## Cursor

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.cursor/projects/<project-path>/agent-transcripts/*.txt` |
| **Windows path** | `%USERPROFILE%\.cursor\projects\<path>\agent-transcripts\*.txt` |
| **Format** | Plain text with `User:` / `Assistant:` / `Human:` / `AI:` prefixes |

**Extraction:**
- Transcripts are `.txt` files in `agent-transcripts/` subdirectories
- Lines prefixed with `User:` or `Human:` map to user messages
- Lines prefixed with `Assistant:` or `AI:` map to assistant messages

**Limitations:** No structured tool call data. Relies on text format that may vary between Cursor versions.

## Copilot CLI

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.copilot/session-state/<session-id>/events.jsonl` |
| **Windows path** | `%USERPROFILE%\.copilot\session-state\<id>\events.jsonl` |
| **Format** | JSONL |

**Extraction:**
- Session directories are sorted by mtime
- `events.jsonl` entries have `type` field with `user.message` and `assistant.message` types
- Message content is in `data.message` or `data.text`

**Limitations:** Tool call information may be limited. Events structure may vary with Copilot CLI version.

## Tool Detection Order

The save script detects the current tool by checking project-level config files first, then falling back to home-directory session storage paths:

1. **OpenCode** — `.opencode.json` or `.opencode.jsonc` in project root
2. **Claude Code** — `CLAUDE.md` or `CLAUDE.txt` in project root
3. **Cursor** — `.cursorrules` in project root
4. **Codex** — `.codex` directory in project root
5. **Copilot CLI** — `.github/copilot-instructions.md` or `.github/copilot/` in project root
