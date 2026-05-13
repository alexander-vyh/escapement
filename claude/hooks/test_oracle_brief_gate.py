#!/usr/bin/env python3
"""Hook gate for requiring a Test Oracle Brief before behavioral code changes.

Claude use:
  PreToolUse on Write/Edit/NotebookEdit/Serena edit tools. Blocks edits to
  code/test files unless .agent/runtime/test-oracle-brief.md exists in the
  repository and contains the required section headings.

Codex use:
  PreToolUse on Bash. Blocks landing/closure commands such as git commit,
  git push, gh pr create, and bd close when code/test files changed but the
  repository lacks a structurally valid Test Oracle Brief.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


BRIEF_RELATIVE_PATH = Path(".agent/runtime/test-oracle-brief.md")

REQUIRED_SECTIONS = (
    "Business invariant",
    "Independent source of truth",
    "Solution constraints",
    "Invalid solution classes",
    "Fragile implementation to reject",
    "Negative control",
    "Positive control",
    "Missing/unresolved handling",
    "Final outcome verification",
)

GATED_EDIT_TOOLS = frozenset(
    {
        "Write",
        "Edit",
        "NotebookEdit",
        "mcp__serena__replace_symbol_body",
        "mcp__serena__insert_after_symbol",
        "mcp__serena__insert_before_symbol",
    }
)

RELATIVE_PATH_TOOLS = frozenset(
    {
        "mcp__serena__replace_symbol_body",
        "mcp__serena__insert_after_symbol",
        "mcp__serena__insert_before_symbol",
    }
)

CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".clj",
        ".cljs",
        ".cs",
        ".fs",
        ".swift",
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hpp",
        ".m",
        ".mm",
        ".php",
        ".ex",
        ".exs",
        ".erl",
        ".hrl",
        ".lua",
        ".pl",
        ".pm",
        ".r",
        ".jl",
        ".zig",
        ".nim",
        ".v",
        ".vue",
        ".svelte",
        ".astro",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
    }
)

TEST_FILE_PATTERNS = (
    re.compile(r"^test_.*\.py$"),
    re.compile(r"^.*_test\.py$"),
    re.compile(r"^conftest\.py$"),
    re.compile(r"^.*\.(test|spec)\.[a-z0-9]+$", re.IGNORECASE),
    re.compile(r"^.*_test\.go$"),
    re.compile(r"^.*_test\.rs$"),
)

EXEMPT_EXTENSIONS = frozenset(
    {
        ".md",
        ".mdx",
        ".rst",
        ".txt",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".env",
        ".csv",
        ".tsv",
        ".html",
        ".css",
        ".scss",
        ".sass",
        ".svg",
        ".xml",
        ".lock",
        ".sum",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".pdf",
    }
)

EXEMPT_DIR_SEGMENTS = frozenset(
    {
        ".agent",
        ".claude",
        ".codex",
        ".git",
        "docs",
        "doc",
        "scripts",
        "bin",
        "tools",
        "scratch",
        "spike",
        "spikes",
        "prototype",
        "prototypes",
        "tmp",
        "vendor",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "__pycache__",
    }
)

FINISHING_COMMANDS = (
    ("git", "commit"),
    ("git", "push"),
    ("gh", "pr", "create"),
    ("gh", "pr", "merge"),
    ("bd", "close"),
)


def allow() -> int:
    return 0


def deny(reason: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 2


def normalize_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def section_present(text: str, section: str) -> bool:
    wanted = normalize_heading(section)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^#{1,6}\s*", "", stripped)
        stripped = re.sub(r"^\d+[.)]\s*", "", stripped)
        stripped = stripped.strip("*_ \t:-")
        if normalize_heading(stripped) == wanted:
            return True
    return False


def missing_brief_sections(brief_path: Path) -> list[str]:
    try:
        text = brief_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(REQUIRED_SECTIONS)
    return [section for section in REQUIRED_SECTIONS if not section_present(text, section)]


def find_git_root(start: str | Path) -> Path | None:
    path = Path(start)
    search_dir = path if path.is_dir() else path.parent
    while not search_dir.exists():
        parent = search_dir.parent
        if parent == search_dir:
            return None
        search_dir = parent

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(search_dir),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def is_test_file(filepath: str) -> bool:
    path = Path(filepath)
    parts = set(path.parts)
    if parts & {"tests", "test", "spec", "__tests__", "__specs__"}:
        return True
    return any(pattern.match(path.name) for pattern in TEST_FILE_PATTERNS)


def is_relevant_file(filepath: str) -> bool:
    path = Path(filepath)
    parts = set(path.parts)

    if path.name == "__init__.py":
        return False
    if parts & EXEMPT_DIR_SEGMENTS:
        return False
    if is_test_file(filepath):
        return True

    suffix = path.suffix.lower()
    if suffix in EXEMPT_EXTENSIONS:
        return False
    return suffix in CODE_EXTENSIONS


def resolve_target_path(filepath: str, cwd: str | None) -> Path:
    path = Path(filepath).expanduser()
    if path.is_absolute():
        return path
    return Path(cwd or os.getcwd()) / path


def brief_status(repo_root: Path) -> tuple[bool, str | None]:
    brief_path = repo_root / BRIEF_RELATIVE_PATH
    if not brief_path.exists():
        return False, f"Missing required Test Oracle Brief: {BRIEF_RELATIVE_PATH}"
    missing = missing_brief_sections(brief_path)
    if missing:
        return (
            False,
            "Test Oracle Brief is missing required section headings: "
            + ", ".join(missing),
        )
    return True, None


def block_message(reason: str, repo_root: Path, files: list[str]) -> str:
    sample_files = "\n".join(f"  - {name}" for name in files[:8])
    if len(files) > 8:
        sample_files += f"\n  - ... {len(files) - 8} more"

    return (
        f"{reason}\n\n"
        "Before editing or landing behavior-bearing code/tests, create:\n"
        f"  {repo_root / BRIEF_RELATIVE_PATH}\n\n"
        "Required headings:\n"
        + "\n".join(f"  - {section}" for section in REQUIRED_SECTIONS)
        + "\n\n"
        "Relevant changed/target files:\n"
        + (sample_files if sample_files else "  - unknown")
    )


def handle_edit_gate(data: dict) -> int:
    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    tool_name = data.get("tool_name", "")
    if hook_event != "PreToolUse" or tool_name not in GATED_EDIT_TOOLS:
        return allow()

    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return allow()

    path_key = "relative_path" if tool_name in RELATIVE_PATH_TOOLS else "file_path"
    raw_path = tool_input.get(path_key) or tool_input.get("file_path") or tool_input.get("relative_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return allow()

    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else None
    target = resolve_target_path(raw_path, cwd)
    repo_root = find_git_root(target)
    if repo_root is None:
        return allow()

    try:
        rel_target = target.relative_to(repo_root).as_posix()
    except ValueError:
        rel_target = raw_path

    if not is_relevant_file(rel_target):
        return allow()

    ok, reason = brief_status(repo_root)
    if ok:
        return allow()
    return deny(block_message(reason or "Invalid Test Oracle Brief.", repo_root, [rel_target]))


def command_from(data: dict) -> str:
    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command")
    return command if isinstance(command, str) else ""


def split_command_segments(command: str) -> list[list[str]]:
    normalized = command.replace("\\\n", " ")
    segments: list[list[str]] = []
    for raw in re.split(r"\s*(?:&&|\|\||;|\|)\s*", normalized):
        try:
            parts = shlex.split(raw)
        except ValueError:
            continue
        if parts:
            segments.append(parts)
    return segments


def is_finishing_segment(parts: list[str]) -> bool:
    for command in FINISHING_COMMANDS:
        if tuple(parts[: len(command)]) == command:
            return True
    return False


def git_files(repo_root: Path, args: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def upstream_ref(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def changed_files_for_landing(repo_root: Path) -> list[str]:
    files: set[str] = set()
    files.update(git_files(repo_root, ["diff", "--name-only"]))
    files.update(git_files(repo_root, ["diff", "--cached", "--name-only"]))
    files.update(git_files(repo_root, ["ls-files", "--others", "--exclude-standard"]))

    upstream = upstream_ref(repo_root)
    if upstream:
        files.update(git_files(repo_root, ["diff", "--name-only", f"{upstream}...HEAD"]))

    return sorted(files)


def handle_bash_landing_gate(data: dict) -> int:
    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    tool_name = data.get("tool_name", "")
    if hook_event != "PreToolUse" or tool_name != "Bash":
        return allow()

    command = command_from(data)
    if not command:
        return allow()
    segments = split_command_segments(command)
    if not any(is_finishing_segment(parts) for parts in segments):
        return allow()

    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
    repo_root = find_git_root(cwd)
    if repo_root is None:
        return allow()

    relevant = [name for name in changed_files_for_landing(repo_root) if is_relevant_file(name)]
    if not relevant:
        return allow()

    ok, reason = brief_status(repo_root)
    if ok:
        return allow()
    return deny(block_message(reason or "Invalid Test Oracle Brief.", repo_root, relevant))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return allow()

    edit_result = handle_edit_gate(data)
    if edit_result != 0:
        return edit_result
    return handle_bash_landing_gate(data)


if __name__ == "__main__":
    raise SystemExit(main())
