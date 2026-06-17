#!/usr/bin/env python3
"""PreToolUse gate: block Write/Edit that would push a file past 500 lines.

500 lines is a complexity signal, not just a LOC count. A file at that length
almost always holds more than one responsibility and becomes hard to navigate,
review, and test atomically. LOC is the practical proxy; the real concern is
coupling between concerns that are better separated into sibling modules.

Exemptions (fail-open on detection failure):
  Path fragments: /vendor/, /node_modules/, /migrations/, /generated/,
                  /testdata/, /fixtures/, /.beads/, /dist/, /build/
  File suffixes:  .pb.go, _pb2.py, .min.js, .min.css, .snap, .lock,
                  -lock.json, .md, .txt, .rst
  Waiver comment: one of the first 5 lines contains
                  `# file-complexity-waiver: <reason>` (or //, --, /* variants)
  Env var:        FILE_COMPLEXITY_WAIVER=<reason>

Escape path IN the denial (gate-design rule 1):
  Extract a cohesive responsibility into a sibling module, OR add a waiver.

Signal (gate-design rule 2):
  Emits to _gate_signal with gate_name='file-complexity'.

Value-not-presence (gate-design rule 3):
  Waiver must be non-empty after the colon; bare marker is rejected.

Exit codes:
  0  — pass (under limit, exempt, or waiver present)
  2  — deny (would exceed 500 lines)
"""

from __future__ import annotations

import json
import os
import sys

LIMIT = 500

_EXEMPT_PATH_FRAGMENTS = (
    "/vendor/",
    "/node_modules/",
    "/migrations/",
    "/generated/",
    "/testdata/",
    "/fixtures/",
    "/.beads/",
    "/dist/",
    "/build/",
)

_EXEMPT_SUFFIXES = (
    ".pb.go",
    "_pb2.py",
    ".min.js",
    ".min.css",
    ".snap",
    ".lock",
    "-lock.json",
    ".md",
    ".txt",
    ".rst",
)

_WAIVER_PREFIXES = (
    "# file-complexity-waiver:",
    "// file-complexity-waiver:",
    "/* file-complexity-waiver:",
    "-- file-complexity-waiver:",
    "<!-- file-complexity-waiver:",
)


def _is_exempt(file_path: str) -> bool:
    norm = file_path.replace(os.sep, "/")
    if any(frag in norm for frag in _EXEMPT_PATH_FRAGMENTS):
        return True
    name = os.path.basename(norm)
    return any(name.endswith(suf) for suf in _EXEMPT_SUFFIXES)


def _has_waiver(first_lines: list[str]) -> bool:
    env_reason = os.environ.get("FILE_COMPLEXITY_WAIVER", "").strip()
    if env_reason:
        return True
    for line in first_lines:
        stripped = line.strip()
        for prefix in _WAIVER_PREFIXES:
            if stripped.startswith(prefix):
                reason = stripped[len(prefix):].strip()
                return bool(reason)  # value-not-presence: reason must be non-empty
    return False


def _emit_signal(decision: str, file_path: str, projected: int) -> None:
    try:
        hooks_dir = os.path.dirname(os.path.abspath(__file__))
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from _gate_signal import record  # type: ignore
        record(
            gate_name="file-complexity",
            decision=decision,
            reason=f"{file_path}: projected {projected} lines (limit {LIMIT})",
            file=file_path,
            projected_lines=projected,
        )
    except Exception:
        pass  # signal capture must never block the gate


def _deny_response(file_path: str, projected: int) -> dict:
    name = os.path.basename(file_path)
    return {
        "permissionDecision": "deny",
        "denyReason": (
            f"{name} would be {projected} lines — a signal it holds too many responsibilities.\n"
            f"Files over {LIMIT} lines become hard to navigate, review, and test atomically.\n\n"
            f"Fix: extract a cohesive responsibility into a sibling module before writing here.\n"
            f"Exempt paths: vendor/, node_modules/, migrations/, generated/, fixtures/, dist/, build/\n"
            f"Bypass: add `# file-complexity-waiver: <reason>` in the first 5 lines of the file,\n"
            f"        or set FILE_COMPLEXITY_WAIVER=<reason> in the environment."
        ),
    }


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path", "")
    if not file_path or _is_exempt(file_path):
        return 0

    try:
        if tool_name == "Write":
            content = tool_input.get("content", "")
            lines = content.splitlines()
            projected = len(lines)
            first_lines = lines[:5]
        else:  # Edit
            try:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    existing = f.read()
            except OSError:
                return 0  # new file or unreadable — fail-open
            existing_lines = existing.splitlines()
            old_string = tool_input.get("old_string", "")
            new_string = tool_input.get("new_string", "")
            delta = len(new_string.splitlines()) - len(old_string.splitlines())
            projected = len(existing_lines) + delta
            first_lines = existing_lines[:5]
    except Exception:
        return 0  # fail-open on any unexpected error

    if projected <= LIMIT:
        return 0

    if _has_waiver(first_lines):
        _emit_signal("waiver-accepted", file_path, projected)
        return 0

    _emit_signal("deny", file_path, projected)
    json.dump(_deny_response(file_path, projected), sys.stdout)
    return 2


if __name__ == "__main__":
    sys.exit(main())
