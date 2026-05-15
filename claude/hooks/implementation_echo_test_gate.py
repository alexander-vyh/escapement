#!/usr/bin/env python3
"""Hook gate for rejecting high-confidence implementation-echo tests.

This is intentionally a landing-time scanner. It compares changed tests with
changed production files and blocks only high-confidence echo patterns:
  - the same generated/opaque literal appears in production code and tests
  - a changed test asserts only mock/private interactions without an outcome

It does not try to prove every test is good. Its job is to stop the most
dangerous deterministic anti-patterns before commit, push, PR, or bd close.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


FINISHING_COMMANDS = (
    ("git", "commit"),
    ("git", "push"),
    ("gh", "pr", "create"),
    ("gh", "pr", "merge"),
    ("bd", "close"),
)

TEST_FILE_PATTERNS = (
    re.compile(r"^test_.*\.py$"),
    re.compile(r"^.*_test\.py$"),
    re.compile(r"^conftest\.py$"),
    re.compile(r"^.*\.(test|spec)\.[a-z0-9]+$", re.IGNORECASE),
    re.compile(r"^.*_test\.go$"),
    re.compile(r"^.*_test\.rs$"),
)

SOURCE_EXTENSIONS = frozenset(
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

STRING_LITERAL_RE = re.compile(
    r"""
    (?P<prefix>[rubfRUBF]{0,3})
    (?P<quote>['"])
    (?P<value>(?:\\.|(?! (?P=quote) ).)*?)
    (?P=quote)
    """,
    re.VERBOSE | re.DOTALL,
)

SALESFORCE_ID_RE = re.compile(r"^(?:001|003|005|006|00Q|012|500|701)[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
HEX_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{24,}$")

PY_TEST_DEF_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+(test_\w+)\s*\(")
PY_MOCK_INTERACTION_RE = re.compile(
    r"(\.assert_(?:called|not_called|called_once|called_once_with|called_with|any_call|has_calls)\b|"
    r"\bassert_(?:called|not_called|called_once|called_once_with|called_with|any_call|has_calls)\b|"
    r"\.mock_calls\b|\.call_args\b|\.call_count\b|\.called\b)"
)
PY_OUTCOME_ASSERTION_RE = re.compile(
    r"(^\s*assert\s+.+(?:==|!=|<=|>=|<|>| in | not in | is | is not ).+|"
    r"pytest\.raises\(|assertRaises\(|assertEqual\(|assertAlmostEqual\(|assertIn\(|assertRegex\()",
    re.MULTILINE,
)

JS_TEST_START_RE = re.compile(r"\b(?:test|it)\s*\(")
JS_MOCK_INTERACTION_RE = re.compile(
    r"\.toHaveBeenCalled(?:Times|With)?\s*\(|\.toHaveBeenNthCalledWith\s*\(|"
    r"\.toHaveBeenLastCalledWith\s*\(|\.mock\.calls\b"
)
JS_OUTCOME_ASSERTION_RE = re.compile(
    r"\.(?:toBe|toEqual|toStrictEqual|toContain|toContainEqual|toMatch|toMatchObject|"
    r"toHaveProperty|toThrow|toBeGreaterThan|toBeLessThan|toBeCloseTo|toHaveLength)\s*\(|"
    r"\.(?:resolves|rejects)\b"
)


@dataclass(frozen=True)
class Issue:
    filepath: str
    kind: str
    detail: str


def allow() -> int:
    return 0


def deny(message: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": message,
                }
            }
        )
    )
    return 2


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


def is_finishing_command(command: str) -> bool:
    for parts in split_command_segments(command):
        for target in FINISHING_COMMANDS:
            if tuple(parts[: len(target)]) == target:
                return True
    return False


def find_git_root(start: str | Path) -> Path | None:
    path = Path(start)
    search_dir = path if path.is_dir() else path.parent
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


def changed_files(repo_root: Path) -> list[str]:
    files: set[str] = set()
    files.update(git_files(repo_root, ["diff", "--name-only"]))
    files.update(git_files(repo_root, ["diff", "--cached", "--name-only"]))
    files.update(git_files(repo_root, ["ls-files", "--others", "--exclude-standard"]))

    upstream = upstream_ref(repo_root)
    if upstream:
        files.update(git_files(repo_root, ["diff", "--name-only", f"{upstream}...HEAD"]))

    return sorted(files)


def is_test_file(filepath: str) -> bool:
    path = Path(filepath)
    parts = set(path.parts)
    if parts & {"tests", "test", "spec", "__tests__", "__specs__"}:
        return True
    return any(pattern.match(path.name) for pattern in TEST_FILE_PATTERNS)


def is_source_file(filepath: str) -> bool:
    path = Path(filepath)
    if set(path.parts) & EXEMPT_DIR_SEGMENTS:
        return False
    if is_test_file(filepath):
        return False
    return path.suffix.lower() in SOURCE_EXTENSIONS


def read_file(repo_root: Path, filepath: str) -> str:
    try:
        return (repo_root / filepath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def string_literals(text: str) -> set[str]:
    values: set[str] = set()
    for match in STRING_LITERAL_RE.finditer(text):
        value = match.group("value")
        if value:
            values.add(value)
    return values


def is_opaque_generated_literal(value: str) -> bool:
    stripped = value.strip()
    if len(stripped) < 12:
        return False
    if any(ch.isspace() for ch in stripped):
        return False
    if stripped.startswith(("http://", "https://", "file://")):
        return False
    if SALESFORCE_ID_RE.match(stripped) or UUID_RE.match(stripped) or HEX_TOKEN_RE.match(stripped):
        return True
    has_alpha = any(ch.isalpha() for ch in stripped)
    has_digit = any(ch.isdigit() for ch in stripped)
    return has_alpha and has_digit and bool(re.match(r"^[A-Za-z0-9_:/+=.-]+$", stripped))


def extract_opaque_literals(files: dict[str, str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for filepath, text in files.items():
        opaque = {value for value in string_literals(text) if is_opaque_generated_literal(value)}
        if opaque:
            result[filepath] = opaque
    return result


def find_shared_generated_literals(source_files: dict[str, str], test_files: dict[str, str]) -> list[Issue]:
    source_literals = extract_opaque_literals(source_files)
    if not source_literals:
        return []

    literal_to_sources: dict[str, list[str]] = {}
    for filepath, values in source_literals.items():
        for value in values:
            literal_to_sources.setdefault(value, []).append(filepath)

    issues: list[Issue] = []
    for test_path, test_values in extract_opaque_literals(test_files).items():
        for value in sorted(test_values):
            source_paths = literal_to_sources.get(value)
            if not source_paths:
                continue
            display = value if len(value) <= 40 else value[:37] + "..."
            issues.append(
                Issue(
                    test_path,
                    "shared-generated-literal",
                    f"opaque literal {display!r} also appears in production file(s): "
                    + ", ".join(source_paths[:4]),
                )
            )
    return issues


_TRIPLE_DQ_RE = re.compile(r'""".*?"""', re.DOTALL)
_TRIPLE_SQ_RE = re.compile(r"'''.*?'''", re.DOTALL)
_LINE_DQ_RE = re.compile(r'"(?:\\.|[^"\\\n])*"')
_LINE_SQ_RE = re.compile(r"'(?:\\.|[^'\\\n])*'")


def blank_string_literals(text: str) -> str:
    """Replace string-literal spans with same-shaped blanks (newlines kept,
    every other char -> space).

    Line-based scanners must not mistake code embedded in a string literal —
    e.g. a `def test_...` fixture inside a pattern-detector's own test file —
    for real code. Triple-quoted strings are blanked first so the single-line
    passes cannot re-match their now-blank interiors. Length is preserved, so
    indentation-based logic downstream is unaffected.
    """
    def _blank(m: "re.Match[str]") -> str:
        return "".join("\n" if c == "\n" else " " for c in m.group(0))

    for pat in (_TRIPLE_DQ_RE, _TRIPLE_SQ_RE, _LINE_DQ_RE, _LINE_SQ_RE):
        text = pat.sub(_blank, text)
    return text


def extract_python_test_functions(text: str) -> list[tuple[str, str]]:
    text = blank_string_literals(text)
    functions: list[tuple[str, str]] = []
    current_name: str | None = None
    current_indent = 0
    current_lines: list[str] = []

    for line in text.splitlines():
        match = PY_TEST_DEF_RE.match(line)
        if match:
            if current_name is not None:
                functions.append((current_name, "\n".join(current_lines)))
            current_name = match.group(2)
            current_indent = len(match.group(1))
            current_lines = []
            continue

        if current_name is not None:
            if line.strip() and len(line) - len(line.lstrip()) <= current_indent and not line.lstrip().startswith(("@", "#")):
                functions.append((current_name, "\n".join(current_lines)))
                current_name = None
                current_lines = []
            else:
                current_lines.append(line)

    if current_name is not None:
        functions.append((current_name, "\n".join(current_lines)))
    return functions


def find_python_mock_only_tests(filepath: str, text: str) -> list[Issue]:
    issues: list[Issue] = []
    for name, body in extract_python_test_functions(text):
        if not PY_MOCK_INTERACTION_RE.search(body):
            continue
        if PY_OUTCOME_ASSERTION_RE.search(body):
            continue
        issues.append(
            Issue(
                filepath,
                "mock-only-test",
                f"{name} asserts mock/private interactions but no observable outcome",
            )
        )
    return issues


def extract_js_test_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not JS_TEST_START_RE.search(line):
            index += 1
            continue

        name_match = re.search(r"(?:test|it)\s*\(\s*['\"]([^'\"]+)['\"]", line)
        name = name_match.group(1) if name_match else f"test block near line {index + 1}"
        block_lines = [line]
        depth = line.count("{") + line.count("(") - line.count("}") - line.count(")")
        index += 1

        while index < len(lines):
            block_lines.append(lines[index])
            depth += lines[index].count("{") + lines[index].count("(")
            depth -= lines[index].count("}") + lines[index].count(")")
            if depth <= 0 and len(block_lines) > 1:
                break
            index += 1

        blocks.append((name, "\n".join(block_lines)))
        index += 1
    return blocks


def find_js_mock_only_tests(filepath: str, text: str) -> list[Issue]:
    issues: list[Issue] = []
    for name, body in extract_js_test_blocks(text):
        if not JS_MOCK_INTERACTION_RE.search(body):
            continue
        if JS_OUTCOME_ASSERTION_RE.search(body):
            continue
        issues.append(
            Issue(
                filepath,
                "mock-only-test",
                f"{name} asserts mock/private interactions but no observable outcome",
            )
        )
    return issues


def find_mock_only_tests(test_files: dict[str, str]) -> list[Issue]:
    issues: list[Issue] = []
    for filepath, text in test_files.items():
        suffix = Path(filepath).suffix.lower()
        if suffix == ".py":
            issues.extend(find_python_mock_only_tests(filepath, text))
        elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            issues.extend(find_js_mock_only_tests(filepath, text))
    return issues


def analyze(repo_root: Path, files: list[str]) -> list[Issue]:
    source_paths = [path for path in files if is_source_file(path)]
    test_paths = [path for path in files if is_test_file(path)]
    if not test_paths:
        return []

    source_files = {path: read_file(repo_root, path) for path in source_paths}
    test_files = {path: read_file(repo_root, path) for path in test_paths}

    issues: list[Issue] = []
    issues.extend(find_shared_generated_literals(source_files, test_files))
    issues.extend(find_mock_only_tests(test_files))
    return issues


def build_message(issues: list[Issue]) -> str:
    listed = "\n".join(
        f"  - {issue.filepath}: {issue.kind}: {issue.detail}" for issue in issues[:12]
    )
    if len(issues) > 12:
        listed += f"\n  - ... {len(issues) - 12} more"
    return (
        "IMPLEMENTATION-ECHO TEST GATE: changed tests contain high-confidence "
        "implementation-echo patterns.\n\n"
        f"{listed}\n\n"
        "Rewrite the tests so they prove observable business/user behavior using "
        "an independent oracle. Do not repeat generated IDs, opaque constants, "
        "or mock/private call structure from the implementation as the oracle."
    )


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return allow()

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    tool_name = data.get("tool_name", "")
    if hook_event != "PreToolUse" or tool_name != "Bash":
        return allow()

    command = command_from(data)
    if not is_finishing_command(command):
        return allow()

    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
    repo_root = find_git_root(cwd)
    if repo_root is None:
        return allow()

    issues = analyze(repo_root, changed_files(repo_root))
    if not issues:
        return allow()
    return deny(build_message(issues))


if __name__ == "__main__":
    raise SystemExit(main())
