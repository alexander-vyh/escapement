#!/usr/bin/env python3
"""PreToolUse gate: two-tier file-length control (soft guidance + hard stop).

Line count is a weak, pragmatic proxy — not a defect/edit-reliability measurement.
The research behind this gate (.research/file-complexity-gate-2026-06-23/) found no
evidence for a defect-reducing file-LOC ceiling; the honest rationale is that >500
lines *correlates* with two real concerns this repo cares about:
  • Humans: the file likely holds more than one responsibility and gets hard to
    review and navigate atomically.
  • Agents: large files inflate the working set; LLM edit reliability degrades as the
    edit target grows (line-number mis-targeting, weaker localization — see arXiv
    2602.16069, 2506.13186). Successful agent edits keep the working set small.

Two tiers:
  SOFT_LIMIT (500)  — exceed → non-blocking `systemMessage` nudge (allowed). A poor
                      proxy, but >500 LOC is where the concerns above start to bite.
  HARD_LIMIT (1000) — exceed → deny (blocked), human-overridable by waiver.

Exemptions (fail-open on detection failure):
  Path fragments: /vendor/, /node_modules/, /migrations/, /generated/,
                  /testdata/, /fixtures/, /.beads/, /dist/, /build/
  File suffixes:  generated code (.pb.go, _pb2.py, _pb2_grpc.py, .gen.go, .g.dart,
                  .freezed.dart, .generated.ts/.js, .pb.cc, .pb.h, go.sum, .min.js,
                  .min.css, .snap, .lock, -lock.json) and passive data/docs
                  (.json, .yaml, .yml, .csv, .tsv, .svg, .ipynb, .geojson, .md,
                  .txt, .rst) — "extract a sibling module" is meaningless for these.
  Waiver comment: one of the first 5 lines contains
                  `# file-complexity-waiver: <reason>` (or //, --, /* variants).
                  Suppresses BOTH tiers (an acknowledged file is not nagged).
  Env var:        FILE_COMPLEXITY_WAIVER=<reason>

Escape path IN the denial (gate-design rule 1):
  Extract a cohesive responsibility into a sibling module, OR add a waiver.

Signal (gate-design rule 2):
  Emits to _gate_signal with gate_name='file-complexity', decision one of
  soft-nudge | deny | waiver-accepted.

Value-not-presence (gate-design rule 3):
  Waiver must be non-empty after the colon; bare marker is rejected.

Exit codes:
  0  — pass (under soft limit, exempt, waiver) or soft nudge (allowed, with message)
  2  — deny (would exceed the hard limit)
"""

from __future__ import annotations

import json
import os
import sys

SOFT_LIMIT = 500
HARD_LIMIT = 1000

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
    # generated code
    ".pb.go",
    ".pb.cc",
    ".pb.h",
    "_pb2.py",
    "_pb2_grpc.py",
    ".gen.go",
    ".g.dart",
    ".freezed.dart",
    ".generated.ts",
    ".generated.js",
    "go.sum",
    ".min.js",
    ".min.css",
    ".snap",
    ".lock",
    "-lock.json",
    # passive data / docs (no logic to extract into a sibling module)
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".svg",
    ".ipynb",
    ".geojson",
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


def decide(projected: int, file_path: str, first_lines: list[str]) -> str:
    """Pure decision core. Returns one of:
    exempt | pass | waiver | soft | hard.

    Ordering matters: exemption first, then the silent-pass band, then waiver
    (which suppresses both the soft nudge and the hard block), then the tiers.
    """
    if _is_exempt(file_path):
        return "exempt"
    if projected <= SOFT_LIMIT:
        return "pass"
    if _has_waiver(first_lines):
        return "waiver"
    if projected <= HARD_LIMIT:
        return "soft"
    return "hard"


def _emit_signal(decision: str, file_path: str, projected: int) -> None:
    try:
        hooks_dir = os.path.dirname(os.path.abspath(__file__))
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from _gate_signal import record  # type: ignore
        record(
            gate_name="file-complexity",
            decision=decision,
            reason=f"{file_path}: projected {projected} lines "
                   f"(soft {SOFT_LIMIT} / hard {HARD_LIMIT})",
            file=file_path,
            projected_lines=projected,
        )
    except Exception:
        pass  # signal capture must never block the gate


def build_soft_message(file_path: str, projected: int) -> str:
    """Non-blocking guidance shown at the soft tier — framed for humans AND agents."""
    name = os.path.basename(file_path)
    return (
        f"{name} is {projected} lines — past the {SOFT_LIMIT}-line guidance threshold "
        f"(soft nudge, not a block; hard stop is {HARD_LIMIT}). Line count is a rough "
        f"proxy for two real concerns:\n"
        f"  • Humans: a file this long usually holds more than one responsibility and "
        f"becomes hard to review and navigate.\n"
        f"  • Agents: large files inflate the working set; LLM edit reliability falls as "
        f"the edit target grows (more line-number mis-targeting, weaker localization).\n"
        f"Consider extracting a cohesive responsibility into a sibling module."
    )


def deny_response(file_path: str, projected: int) -> dict:
    """Blocking response at the hard tier — carries the human override path."""
    name = os.path.basename(file_path)
    return {
        "permissionDecision": "deny",
        "denyReason": (
            f"{name} would be {projected} lines — past the {HARD_LIMIT}-line hard limit "
            f"(guidance starts at {SOFT_LIMIT}).\n"
            f"Files this large hurt both reviewers (multiple responsibilities, hard to "
            f"review atomically) and agents (working set too large; edit-target ambiguity "
            f"and line-number errors rise sharply).\n\n"
            f"Fix: extract a cohesive responsibility into a sibling module before writing here.\n"
            f"Exempt paths: vendor/, node_modules/, migrations/, generated/, fixtures/, dist/, build/\n"
            f"Human override: add `# file-complexity-waiver: <reason>` in the first 5 lines of "
            f"the file, or set FILE_COMPLEXITY_WAIVER=<reason> in the environment."
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
        return 0  # exempt short-circuit: skip the file read entirely

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

    decision = decide(projected, file_path, first_lines)

    if decision in ("exempt", "pass"):
        return 0

    if decision == "waiver":
        _emit_signal("waiver-accepted", file_path, projected)
        return 0

    if decision == "soft":
        _emit_signal("soft-nudge", file_path, projected)
        json.dump({"systemMessage": build_soft_message(file_path, projected)}, sys.stdout)
        return 0

    # decision == "hard"
    _emit_signal("deny", file_path, projected)
    json.dump(deny_response(file_path, projected), sys.stdout)
    return 2


if __name__ == "__main__":
    sys.exit(main())
