# Tool Session Sources

Detailed session file locations and extraction notes for each supported tool.

## OpenCode

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.local/share/opencode/opencode.db` |
| **Windows path** | `%LOCALAPPDATA%\opencode\opencode.db` |
| **Format** | SQLite |
| **Tables used** | `session`, `message`, `part` |
| **Schema notes** | `message.data` contains metadata (role, agent, model). Actual conversation content lives in the `part` table keyed by `message_id`. Each part has a `type` field: `text` (user/assistant text), `reasoning` (thinking), `tool` (tool calls with input/output), `step-start`/`step-finish` (metadata). |

**Extraction:**
- The DB is safely copied via `sqlite3.backup()` before querying
- Sessions are matched to the current project via the `path` JSON column (`root`/`cwd`)
- Conversation is reconstructed by reading `part` rows for each message, extracting `text` and `reasoning` parts
- Tool calls are extracted from `part` rows where `type = "tool"`, capturing `tool`, `state.input`, and `state.output`

**Limitations:** Tool call outputs may be truncated by OpenCode. Compaction messages (`type = "compaction"`) are skipped.

## Claude Code

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.claude/projects/<project-hash>/` |
| **Windows path** | `%USERPROFILE%\.claude\projects\<hash>\` |
| **Format** | JSONL (one JSON object per line) |
| **Line types** | `user`, `assistant`, `tool_use` |

**Extraction:**
- The project directory name is path-encoded (`:` → `-`, `/` → `-`, `\` → `-`)
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
| **Unix path** | `~/.copilot/session-state/<session-uuid>/` |
| **Windows path** | `%USERPROFILE%\.copilot\session-state\<uuid>\` |
| **Format** | YAML workspace + Markdown checkpoints |
| **Key files** | `workspace.yaml`, `checkpoints/index.md` |

**Extraction:**
- Session directories sorted by mtime
- `workspace.yaml` contains session metadata: `id`, `cwd`, `summary_count`, `created_at`, `updated_at`
- `checkpoints/index.md` contains a markdown table of file checkpoints

**Limitations:** Copilot CLI (v1.0+) does not persist conversation text. Only workspace metadata and file checkpoints are available. The extractor returns a metadata-only USF with empty conversation.

## Gemini CLI

| Detail | Value |
|--------|-------|
| **Unix path** | `~/.gemini/tmp/<project-slug>/chats/session-*.json` |
| **Windows path** | `%USERPROFILE%\.gemini\tmp\<slug>\chats\session-*.json` |
| **Project mapping** | `~/.gemini/projects.json` maps project directories to slugs |
| **Format** | JSON |

**Extraction:**
- Read `~/.gemini/projects.json` to find the project slug for the current directory
- Glob `~/.gemini/tmp/<slug>/chats/session-*.json`, pick most recent
- Each session file is a JSON object with `sessionId`, `projectHash`, `startTime`, `lastUpdated`, `messages[]`, `kind`
- Messages have `id`, `timestamp`, `type` (`user`/`assistant`/`info`/`tool`), and `content`

**Limitations:** Sessions in `tmp/` may be cleaned up by Gemini CLI. Message types need verification against real conversations — the observed sessions only contain `info`-type system messages (auth, updates).

## Tool Detection

Detection is handled by `cf/scripts/cf-detect.py` — a standalone module that uses environment variables and process-tree topology. It distinguishes `immediate_agent` (closest agent in parent chain), `root_agent` (topmost agent), `terminal_host` (IDE/terminal), and `sandbox` (CI/containers).

### Phase 1: cf-detect (env vars + process tree — definitive)

| Tool | Environment Variables | Process Signatures |
|------|----------------------|--------------------|
| **Claude Code** | `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` | `@anthropic-ai/claude`, `claude-code` |
| **Codex** | `CODEX_ENV`, `OPENAI_CODEX`, `CODEX_HOME` | `@openai/codex`, `codex-cli` |
| **OpenCode** | `OPENCODE`, `OPENCODE_SESSION` | `@opencode-ai/`, `opencode-cli` |
| **GitHub Copilot CLI** | `COPILOT_AGENT_ID`, `COPILOT_AGENT_TOKEN`, `GH_COPILOT_TOKEN` | `@github/copilot`, `gh-copilot` |
| **Gemini CLI** | `GEMINI_SANDBOX`, `GEMINI_CLI_*` | `@google/gemini-cli`, `gemini-cli` |

### Phase 2: Terminal host fallback

If no agent is detected, checks `terminal_host` (e.g. running inside Cursor's terminal). Maps `Cursor` → CURSOR tool ID.

### Phase 3: Most recently active session (last resort)

Checks mtime of session files for each tool and picks the most recently modified one. Unreliable when tools run concurrently — only used when env vars and process tree yield nothing.
