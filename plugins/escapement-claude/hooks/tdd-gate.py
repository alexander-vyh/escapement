#!/usr/bin/env python3
"""PreToolUse hook: TDD enforcement — test before implementation.

Fires as PreToolUse on Write, Edit and NotebookEdit (Claude Code; Pi maps its
write/edit onto them) and on apply_patch (Codex). A patch can name several
files; one that writes a test file is TDD in progress, like a Write to a test.

When writing to an implementation file in a code project — one with test
infrastructure or a language project manifest — checks that test files have
been modified in the working tree first. If no test files are modified,
prompts the user to confirm. Greenfield counts: a project whose tests/ dir
does not exist yet is exactly where the question is still open.

Severity: ask (not block) — the user can always override. Codex runs a
PreToolUse `ask` as an allow and tells the model nothing (captured on 0.156.1,
tests/fixtures/codex_hook_payloads.json), so on apply_patch the same question
is a deny that fires once per file per session: re-applying the patch is the
override, as answering the prompt is on Claude. The Pi extension runs `ask` as
a block, so a Pi write or edit gets the same once-per-file deny, and making the
same write or edit again is the override.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input (cwd, session_id)
Exit codes:
  0 — always; the decision is the JSON on stdout
"""

# PEP 604 annotations below are evaluated when each def executes, so without
# this import the module raises TypeError on import under Python 3.9.
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _advisory_dedupe import already_reported_any as _already_seen
    from _advisory_dedupe import clear as _forget_seen
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None

    def _already_seen(*_args, **_kwargs) -> bool:
        return False

    def _forget_seen(*_args, **_kwargs) -> None:
        return None

import _host_output  # noqa: E402
from _agent_dispatch import host as _host  # noqa: E402
from _serena_tools import is_serena_edit  # noqa: E402

try:
    from _codex_patch import payload_targets as _patch_targets
except ImportError:  # pragma: no cover - fail open: no patch, nothing to judge
    def _patch_targets(*_args, **_kwargs):
        return None


# ---------------------------------------------------------------------------
# Gated tools
# ---------------------------------------------------------------------------

# Tools that write/edit code and therefore go through the TDD nudge.
# Serena's symbol-editing tools (any host's spelling, see _serena_tools) and
# NotebookEdit modify implementation code the same way Write/Edit do, so they
# get the same treatment.
_GATED_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})

# Tool-input keys that carry the target file path, in priority order.
# Serena tools use relative_path; NotebookEdit uses notebook_path.
_FILE_PATH_KEYS = ("file_path", "relative_path", "notebook_path")


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

# Extensions that are never "implementation code"
_EXEMPT_EXTENSIONS = frozenset({
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".env",
    ".md", ".rst", ".txt",
    ".html", ".css", ".svg",
    ".lock", ".gitignore", ".dockerignore",
    ".sh", ".bash",
    ".sql",
})

# Directory segments that indicate throwaway / non-production code
_EXEMPT_DIR_SEGMENTS = frozenset({
    "scripts", "bin", "tools", "scratch", "spike", "prototype",
    "docs", "doc", "migrations", "alembic",
})

# Test file patterns
_TEST_PATTERNS: list[re.Pattern] = [
    # Python
    re.compile(r"^test_.*\.py$"),
    re.compile(r"^.*_test\.py$"),
    re.compile(r"^conftest\.py$"),
    # JS/TS
    re.compile(r"^.*\.test\.\w+$"),
    re.compile(r"^.*\.spec\.\w+$"),
    # Go
    re.compile(r"^.*_test\.go$"),
    # Rust (test modules are inline, but test files may exist)
    re.compile(r"^.*_test\.rs$"),
]


def is_test_file(filepath: str) -> bool:
    """Check if a file path looks like a test file."""
    name = os.path.basename(filepath)
    parts = set(Path(filepath).parts)

    # File in a tests/ or test/ or __tests__/ directory
    if parts & {"tests", "test", "__tests__"}:
        return True

    # Filename matches test patterns
    return any(p.match(name) for p in _TEST_PATTERNS)


def is_exempt_file(filepath: str) -> bool:
    """Check if a file is exempt from TDD enforcement."""
    name = os.path.basename(filepath)
    ext = os.path.splitext(name)[1].lower()

    # Exempt extensions
    if ext in _EXEMPT_EXTENSIONS:
        return True

    # Exempt directory segments
    parts = set(Path(filepath).parts)
    if parts & _EXEMPT_DIR_SEGMENTS:
        return True

    # __init__.py files (structural, not behavioral)
    if name == "__init__.py":
        return True

    return False


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def find_git_root(filepath: str) -> str | None:
    """Find the git repo root for a given file path.

    Walks up from the file's directory to find the nearest existing parent,
    since the target file (and its immediate parent) may not exist yet.
    """
    search_dir = Path(filepath).parent
    while not search_dir.is_dir():
        parent = search_dir.parent
        if parent == search_dir:
            return None  # hit filesystem root
        search_dir = parent

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
            cwd=str(search_dir),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def has_tests_directory(repo_root: str) -> bool:
    """Check if the repo has test infrastructure.

    Recognized across ecosystems:
      - a tests/, test/, or spec/ directory
      - Rust:    Cargo.toml
      - Go:      go.mod
      - Elixir:  mix.exs
      - JS/TS:   package.json that declares a "test" script

    A package.json without a "test" script does NOT count on its own — many
    JS projects have one with only build/lint scripts and no test harness.
    """
    root = Path(repo_root)

    # Test directories (plural and singular, plus RSpec-style spec/)
    for dirname in ("tests", "test", "spec"):
        if (root / dirname).is_dir():
            return True

    # Single-file ecosystem markers that imply a built-in test harness
    for marker in ("Cargo.toml", "go.mod", "mix.exs"):
        if (root / marker).is_file():
            return True

    # JS/TS: only counts when a "test" script is actually declared
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
        scripts = data.get("scripts") if isinstance(data, dict) else None
        if isinstance(scripts, dict) and scripts.get("test"):
            return True

    return False


# Files that mark a directory as a code project even before any test exists.
_PROJECT_MANIFESTS = frozenset({
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",  # Python
    "package.json",                                                  # JS/TS
    "Cargo.toml",                                                    # Rust
    "go.mod",                                                        # Go
    "mix.exs",                                                       # Elixir
    "Gemfile",                                                       # Ruby
    "pom.xml", "build.gradle", "build.gradle.kts",                    # JVM
    "composer.json",                                                 # PHP
})


def has_project_manifest(repo_root: str) -> bool:
    """Check whether the repo is a code project at all.

    `has_tests_directory` answers "does test infrastructure already exist",
    which is false for every greenfield project at the moment of its first
    implementation write — precisely when the nudge matters most, and after
    which the repo still has no tests/ dir, so the exemption would hold
    forever. This answers the weaker question the gate actually needs: is
    this a code project, as opposed to a docs or config repo where a TDD
    prompt would be noise.
    """
    root = Path(repo_root)
    return any((root / name).is_file() for name in _PROJECT_MANIFESTS)


def get_modified_files(repo_root: str) -> list[str]:
    """Get all modified, staged, and untracked files in the working tree."""
    files: list[str] = []

    try:
        # Unstaged modifications
        r1 = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        if r1.returncode == 0:
            files.extend(f for f in r1.stdout.strip().split("\n") if f)

        # Staged modifications
        r2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        if r2.returncode == 0:
            files.extend(f for f in r2.stdout.strip().split("\n") if f)

        # Untracked new files
        r3 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        if r3.returncode == 0:
            files.extend(f for f in r3.stdout.strip().split("\n") if f)

    except (subprocess.TimeoutExpired, OSError):
        pass

    return files


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def allow() -> int:
    """Allow the action."""
    return 0


def ask(hook_event: str, message: str) -> int:
    """Prompt the user for confirmation.

    CANONICAL DECISION CONTRACT: signal the decision with a single mechanism —
    one permissionDecision JSON document on stdout, exit 0. Exit 2 is the
    mutually-exclusive legacy stderr-feedback path; emitting both the JSON
    decision *and* a non-zero exit is a contradictory double-signal. This gate
    is advisory (permissionDecision="ask"), but uses the same single-mechanism
    JSON-on-stdout-plus-exit-0 contract as the hard-deny gates, so it returns 0.
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "ask",
            "permissionDecisionReason": message,
        }
    }))
    return 0


def ask_without_prompt(message: str, session_id: str, retry: str) -> int:
    """The same question on a host where `ask` prompts no one.

    Codex runs `ask` as an allow and the Pi extension runs it as a block, so
    neither can take "say 'proceed'" for an answer. This is a deny, made
    escapable by the per-session dedupe: retrying the call (`retry` names how,
    in the host's own tool words) finds the file already reported and passes.
    Without a session id that dedupe cannot hold, so a deny would block every
    retry -- the question is then delivered as model context instead.
    """
    if not session_id:
        print(json.dumps(_host_output.advisory(message)))
        return 0
    print(json.dumps(_host_output.deny(
        f"{message} To go ahead without a test, {retry}: "
        f"this check blocks only once per file per session."
    )))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def written_files(tool_name: str, tool_input: dict, cwd: str) -> list[str]:
    """Every file this call writes: one per built-in edit, any number per patch."""
    if tool_name == "apply_patch":
        found = _patch_targets(tool_input, cwd) or []
        return [path for kind, path in found if kind != "Delete"]
    for key in _FILE_PATH_KEYS:
        value = tool_input.get(key)
        if value:
            return [value]
    return []


def nudge_for(filepath: str, session_id: str) -> str | None:
    """The repo-relative path to nudge about, or None when the write is fine."""
    # Exempt file type (config, docs, scripts, etc.)?
    if is_exempt_file(filepath):
        return None

    # Not in a git repo? Allow — not "actual dev"
    repo_root = find_git_root(filepath)
    if not repo_root:
        return None

    # Neither test infrastructure nor a code-project manifest? Allow — a docs
    # or config repo is not "actual dev". Test infrastructure alone is not
    # enough of a signal: requiring it made the gate silent on greenfield,
    # where the presence of tests is still an open question.
    if not (has_tests_directory(repo_root) or has_project_manifest(repo_root)):
        return None

    # --- TDD enforcement ---

    # Check if any test files have been modified in the working tree
    modified_files = get_modified_files(repo_root)
    has_test_changes = any(is_test_file(f) for f in modified_files)

    rel_path = os.path.relpath(filepath, repo_root)

    if has_test_changes:
        # The condition this gate exists to flag is resolved, so the memory of
        # having flagged it must go too. Leaving it would silence the gate for
        # the rest of the session once tests are touched and then abandoned.
        _forget_seen("tdd_gate", str(session_id))
        _record_signal(
            gate_name="tdd_gate",
            decision="allow",
            reason="test files already modified in working tree",
            file=rel_path,
        )
        return None

    # No test files modified — nudge toward TDD, but only about a file this
    # session has not already been nudged about. The advice does not depend on
    # which file triggered it, and repeating it trains the reader to skip it.
    if _already_seen("tdd_gate", str(session_id), rel_path):
        _record_signal(
            gate_name="tdd_gate",
            decision="allow",
            reason="already nudged about this file in this session",
            file=rel_path,
        )
        return None
    return rel_path


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if hook_event != "PreToolUse":
        return 0
    if (tool_name not in _GATED_TOOLS and tool_name != "apply_patch"
            and not is_serena_edit(tool_name)):
        return 0
    if not isinstance(tool_input, dict):
        return 0
    files = written_files(tool_name, tool_input, str(data.get("cwd") or ""))
    if not files:
        return 0

    # Writing a test file? Always allow — this IS TDD
    if any(is_test_file(path) for path in files):
        return allow()

    session_id = str(data.get("session_id") or data.get("sessionId") or "")
    nudges = [rel for rel in (nudge_for(path, session_id) for path in files) if rel]
    if not nudges:
        return allow()

    shown = "', '".join(nudges)
    _record_signal(
        gate_name="tdd_gate",
        decision="ask",
        reason="writing impl file with no test changes in working tree",
        file=nudges[0] if len(nudges) == 1 else nudges,
    )
    found = f"TDD: writing to '{shown}' but no test files have been modified yet."
    # Only Claude prompts the user on `ask`; elsewhere the retry is the answer.
    if tool_name == "apply_patch":
        return ask_without_prompt(
            f"{found} Write the failing test first.", session_id, "apply the same patch again"
        )
    if _host(data) == "pi":
        return ask_without_prompt(
            f"{found} Write the failing test first.", session_id, "make the same write or edit again"
        )
    return ask(
        hook_event,
        f"{found} Write the failing test first, or say 'proceed' to skip TDD for this change.",
    )


if __name__ == "__main__":
    sys.exit(main())
