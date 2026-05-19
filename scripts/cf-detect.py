"""
Agentic tool runtime detector.

Production-ready, best-effort detection of the current agentic coding tool
context using environment variables and process-tree topology.

Key design goals:
- Do not rely on workspace files.
- Work when multiple agentic tools run in the same directory.
- Distinguish:
  - immediate_agent: closest agent in the parent chain
  - root_agent: top-most detected agent in the parent chain
  - terminal_host: IDE/terminal host like Cursor / VS Code
  - sandbox: CI / Codespaces / Dev Container / WSL / OpenHands
- Treat process-tree topology as authoritative when available.
- Degrade gracefully when psutil is unavailable.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class DetectionResult:
    immediate_agent: Optional[str] = None
    root_agent: Optional[str] = None
    terminal_host: Optional[str] = None
    sandbox: Optional[str] = None
    is_ci: bool = False
    is_remote: bool = False
    is_tty: bool = True
    confidence: str = "low"
    evidence: List[str] = field(default_factory=list)

    def primary(self) -> str:
        return (
            self.immediate_agent
            or self.root_agent
            or self.terminal_host
            or self.sandbox
            or "Standard Terminal or Unknown Agent"
        )


AGENT_PROCESS_SIGNATURES: List[Tuple[str, List[str]]] = [
    ("Claude Code", [
        "@anthropic-ai/claude",
        "claude-code",
        "/claude-code/",
        "/.claude/",
    ]),
    ("Codex", [
        "@openai/codex",
        "codex-cli",
        "openai-codex",
        "/.codex/",
    ]),
    ("OpenCode", [
        "@opencode-ai/",
        "/opencode/",
        "opencode-cli",
    ]),
    ("OpenHands", [
        "openhands",
        "opendevin",
    ]),
    ("GitHub Copilot CLI", [
        "@github/copilot",
        "gh-copilot",
        "gh copilot",
        "/copilot-cli/",
    ]),
    ("Gemini CLI", [
        "@google/gemini-cli",
        "/gemini-cli/",
        "gemini-cli",
    ]),
]

TERMINAL_PROCESS_SIGNATURES: List[Tuple[str, List[str]]] = [
    ("Cursor", [
        "cursor.app",
        "cursor.exe",
        "cursor-server",
        "cursor helper",
        "/cursor/",
    ]),
    ("VS Code", [
        "visual studio code",
        "microsoft vs code",
        "vscode-server",
        "/.vscode-server/",
        "/code.app/",
        "code - oss",
    ]),
]

ROOT_PROCESSES = {
    "init",
    "systemd",
    "launchd",
    "wininit.exe",
    "services.exe",
    "explorer.exe",
}

CI_MARKERS = (
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "CIRCLECI",
    "JENKINS_URL",
    "BUILDKITE",
    "TRAVIS",
    "TEAMCITY_VERSION",
    "TF_BUILD",
)

STRONG_ENV_AGENT_EVIDENCE: Dict[str, Tuple[str, ...]] = {
    "Claude Code": (
        "env:CLAUDECODE / CLAUDE_CODE_ENTRYPOINT",
    ),
    "Codex": (
        "env:CODEX_*",
    ),
    "OpenCode": (
        "env:OPENCODE / OPENCODE_SESSION",
    ),
    "OpenHands": (
        "env:OPENHANDS_WORKSPACE",
    ),
    "GitHub Copilot CLI": (
        "env:COPILOT_AGENT_* / GH_COPILOT_TOKEN",
    ),
    "Gemini CLI": (
        "env:GEMINI_SANDBOX / GEMINI_CLI_*",
    ),
}


def _normalize_path(text: str) -> str:
    return text.replace("\\", "/").lower()


def _safe_cmdline(process) -> str:
    try:
        return _normalize_path(" ".join(process.cmdline()))
    except Exception:
        return ""


def _safe_name(process) -> str:
    try:
        return process.name().lower()
    except Exception:
        return ""


def _get_parent_chain(process, max_depth: int = 30) -> List:
    parents: List = []
    seen = set()
    current = process

    for _ in range(max_depth):
        try:
            parent = current.parent()
        except Exception:
            break

        if parent is None:
            break

        try:
            pid = parent.pid
        except Exception:
            break

        if pid in seen:
            break

        seen.add(pid)
        parents.append(parent)
        current = parent

    return parents


def _match_signature(text: str, signatures: Sequence[Tuple[str, Sequence[str]]]) -> Tuple[Optional[str], Optional[str]]:
    for name, keywords in signatures:
        for keyword in keywords:
            if keyword in text:
                return name, keyword
    return None, None


def _has_strong_env_evidence_for(agent_name: Optional[str], evidence: Sequence[str]) -> bool:
    if not agent_name:
        return False
    markers = STRONG_ENV_AGENT_EVIDENCE.get(agent_name, ())
    return any(marker in evidence for marker in markers)


def _detect_from_env(result: DetectionResult) -> None:
    env = os.environ

    if env.get("CLAUDECODE") == "1" or env.get("CLAUDE_CODE_ENTRYPOINT"):
        result.immediate_agent = result.immediate_agent or "Claude Code"
        result.confidence = "high"
        result.evidence.append("env:CLAUDECODE / CLAUDE_CODE_ENTRYPOINT")

    if env.get("CODEX_ENV") or env.get("OPENAI_CODEX") or env.get("CODEX_HOME"):
        result.immediate_agent = result.immediate_agent or "Codex"
        result.confidence = "high"
        result.evidence.append("env:CODEX_*")

    if env.get("OPENCODE") or env.get("OPENCODE_SESSION"):
        result.immediate_agent = result.immediate_agent or "OpenCode"
        result.confidence = "high"
        result.evidence.append("env:OPENCODE / OPENCODE_SESSION")

    if env.get("OPENHANDS_WORKSPACE") or env.get("SANDBOX_VOLUMES"):
        result.immediate_agent = result.immediate_agent or "OpenHands"
        result.sandbox = result.sandbox or "OpenHands Workspace"
        result.confidence = "high"
        result.evidence.append("env:OPENHANDS_WORKSPACE")

    copilot_markers = (
        "COPILOT_AGENT_ID",
        "COPILOT_AGENT_TOKEN",
        "GH_COPILOT_TOKEN",
        "GITHUB_COPILOT_CLI",
    )
    if any(env.get(k) for k in copilot_markers):
        result.immediate_agent = result.immediate_agent or "GitHub Copilot CLI"
        result.confidence = "high"
        result.evidence.append("env:COPILOT_AGENT_* / GH_COPILOT_TOKEN")

    if env.get("GEMINI_SANDBOX") or any(k.startswith("GEMINI_CLI_") for k in env.keys()):
        result.immediate_agent = result.immediate_agent or "Gemini CLI"
        result.confidence = "high"
        result.evidence.append("env:GEMINI_SANDBOX / GEMINI_CLI_*")
    elif env.get("GEMINI_API_KEY"):
        result.evidence.append("env:GEMINI_API_KEY (weak)")

    term_program = env.get("TERM_PROGRAM", "")
    if term_program == "Cursor":
        result.terminal_host = result.terminal_host or "Cursor"
        result.evidence.append("env:TERM_PROGRAM=Cursor")
    elif term_program == "vscode":
        result.terminal_host = result.terminal_host or "VS Code"
        result.evidence.append("env:TERM_PROGRAM=vscode")

    ipc_hook = env.get("VSCODE_IPC_HOOK_CLI", "").lower()
    if "cursor" in ipc_hook:
        result.terminal_host = result.terminal_host or "Cursor"
        result.evidence.append("env:VSCODE_IPC_HOOK_CLI~cursor")
    elif ipc_hook:
        result.terminal_host = result.terminal_host or "VS Code"
        result.evidence.append("env:VSCODE_IPC_HOOK_CLI~vscode")

    if env.get("CODESPACES") == "true":
        result.sandbox = result.sandbox or "GitHub Codespaces"
        result.is_remote = True
        result.evidence.append("env:CODESPACES=true")

    if env.get("REMOTE_CONTAINERS") == "true" or env.get("DEVCONTAINER"):
        result.sandbox = result.sandbox or "Dev Container"
        result.evidence.append("env:Dev Container")

    if "WSL_DISTRO_NAME" in env or "WSLENV" in env:
        result.sandbox = result.sandbox or "WSL"
        result.evidence.append("env:WSL")

    if env.get("SSH_CONNECTION") or env.get("SSH_CLIENT"):
        result.is_remote = True
        result.evidence.append("env:SSH session")

    if any(env.get(m) for m in CI_MARKERS) or env.get("CI") == "true":
        result.is_ci = True
        result.sandbox = result.sandbox or "CI"
        result.evidence.append("env:CI environment")


def _detect_from_process_tree(result: DetectionResult) -> None:
    if not HAS_PSUTIL:
        result.evidence.append("process:psutil unavailable, skipped")
        return

    try:
        current = psutil.Process(os.getpid())
    except Exception:
        result.evidence.append("process:cannot read self process")
        return

    agent_matches: List[Tuple[str, str]] = []
    terminal_matches: List[Tuple[str, str]] = []

    for parent in _get_parent_chain(current):
        name = _safe_name(parent)
        cmdline = _safe_cmdline(parent)

        if name in ROOT_PROCESSES:
            break
        if not cmdline:
            continue

        agent, keyword = _match_signature(cmdline, AGENT_PROCESS_SIGNATURES)
        if agent:
            agent_matches.append((agent, keyword or ""))

        terminal, t_keyword = _match_signature(cmdline, TERMINAL_PROCESS_SIGNATURES)
        if terminal:
            terminal_matches.append((terminal, t_keyword or ""))

    if agent_matches:
        immediate, immediate_kw = agent_matches[0]
        root, root_kw = agent_matches[-1]

        if result.immediate_agent and result.immediate_agent != immediate:
            result.evidence.append(
                f"process: overriding env agent '{result.immediate_agent}' -> '{immediate}' based on topology"
            )
            result.confidence = "medium"

        result.immediate_agent = immediate
        result.root_agent = root
        result.evidence.append(f"process:immediate agent matched '{immediate_kw}'")

        if root != immediate:
            result.evidence.append(f"process:root agent matched '{root_kw}'")

    if terminal_matches:
        terminal, t_keyword = terminal_matches[0]

        if result.terminal_host and result.terminal_host != terminal:
            result.evidence.append(
                f"process: overriding env terminal '{result.terminal_host}' -> '{terminal}' based on topology"
            )

        result.terminal_host = terminal
        result.evidence.append(f"process:terminal host matched '{t_keyword}'")


def _detect_tty(result: DetectionResult) -> None:
    try:
        result.is_tty = sys.stdin.isatty()
    except Exception:
        result.is_tty = False

    if not result.is_tty:
        result.evidence.append("io:stdin not a tty (likely non-interactive caller)")


_cached_result: Optional[DetectionResult] = None


def detect_agent_context(refresh: bool = False) -> DetectionResult:
    global _cached_result

    if _cached_result is not None and not refresh:
        return deepcopy(_cached_result)

    result = DetectionResult()

    _detect_from_env(result)
    _detect_from_process_tree(result)
    _detect_tty(result)

    if result.immediate_agent:
        if result.confidence == "low":
            result.confidence = "medium"

        was_overridden = any("process: overriding env agent" in ev for ev in result.evidence)

        if (
            not was_overridden
            and result.confidence == "medium"
            and _has_strong_env_evidence_for(result.immediate_agent, result.evidence)
        ):
            result.confidence = "high"

    elif result.terminal_host or result.sandbox:
        if result.confidence == "low":
            result.confidence = "medium"

    if not HAS_PSUTIL and result.immediate_agent and not _has_strong_env_evidence_for(result.immediate_agent, result.evidence):
        result.confidence = "low"

    _cached_result = result
    return deepcopy(result)


def clear_cache() -> None:
    global _cached_result
    _cached_result = None


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    ctx = detect_agent_context(refresh=True)
    print(f"primary           : {ctx.primary()}")
    print(f"immediate_agent   : {ctx.immediate_agent or 'Unknown'}")
    print(f"root_agent        : {ctx.root_agent or 'Unknown'}")
    print(f"terminal_host     : {ctx.terminal_host or 'Unknown'}")
    print(f"sandbox           : {ctx.sandbox or 'Unknown'}")
    print(f"is_ci             : {ctx.is_ci}")
    print(f"is_remote         : {ctx.is_remote}")
    print(f"is_tty            : {ctx.is_tty}")
    print(f"confidence        : {ctx.confidence}")
    print("evidence          :")
    for item in ctx.evidence:
        print(f"  - {item}")
