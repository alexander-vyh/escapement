#!/usr/bin/env python3
"""Query the gate-signal log (.beads/.gate-signal.jsonl).

The canonical reader for signals captured by claude/hooks/_gate_signal.py.
Per claude/rules/gate-design.md Rule 2: "every gate produces persistent
signal." This script consumes that signal so the user can answer:

  - How many times did each gate fire in the last N days?
  - What were the reason texts captured for denials and waivers?
  - Are any gates uniformly allow (likely bloat — never blocks anyone)?

## Usage

    python3 claude/bin/gate_signal_query.py [--since 1d|7d|30d]
                                            [--gate <gate_name>]
                                            [--decision <decision>]
                                            [--json]

Default output is a human-readable summary. Pass --json for machine
output suitable for piping into jq.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_SIGNAL_FILENAME = ".gate-signal.jsonl"


def _resolve_signal_path() -> Path | None:
    """Mirror of _gate_signal._resolve_signal_path."""
    beads_dir_env = os.environ.get("BEADS_DIR")
    if beads_dir_env:
        candidate = Path(beads_dir_env)
        if candidate.is_dir():
            return candidate / _SIGNAL_FILENAME

    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        beads = parent / ".beads"
        if beads.is_dir():
            return beads / _SIGNAL_FILENAME

    return None


def _parse_since(token: str) -> timedelta:
    """Parse '1d', '7d', '24h', '30m' into a timedelta."""
    if not token:
        return timedelta(days=365)  # effectively "no filter"
    suffix_map = {"d": "days", "h": "hours", "m": "minutes"}
    suffix = token[-1].lower()
    if suffix not in suffix_map:
        raise ValueError(f"unrecognized suffix in --since '{token}'")
    try:
        value = int(token[:-1])
    except ValueError as e:
        raise ValueError(f"non-integer value in --since '{token}'") from e
    return timedelta(**{suffix_map[suffix]: value})


def _read_entries(
    signal_path: Path, since: timedelta,
    gate_filter: str | None, decision_filter: str | None,
) -> list[dict[str, Any]]:
    """Read entries from the JSONL file, filtered by since / gate / decision."""
    if not signal_path.is_file():
        return []

    cutoff = datetime.now(timezone.utc) - since
    entries: list[dict[str, Any]] = []

    with open(signal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip corrupted lines

            ts_str = entry.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue

            if gate_filter and entry.get("gate") != gate_filter:
                continue
            if decision_filter and entry.get("decision") != decision_filter:
                continue

            entries.append(entry)

    return entries


def _summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce a summary dict: counts by gate, by decision, sample reasons."""
    by_gate: Counter[str] = Counter()
    by_gate_decision: dict[str, Counter[str]] = defaultdict(Counter)
    reasons_by_gate: dict[str, list[str]] = defaultdict(list)

    for entry in entries:
        gate = entry.get("gate", "?")
        decision = entry.get("decision", "?")
        reason = entry.get("reason", "")
        by_gate[gate] += 1
        by_gate_decision[gate][decision] += 1
        if reason:
            reasons_by_gate[gate].append(reason)

    # Flag gates that are uniformly allow — possibly bloat (never blocks)
    uniformly_allow = [
        gate for gate, decisions in by_gate_decision.items()
        if set(decisions.keys()) == {"allow"} and by_gate[gate] >= 5
    ]

    return {
        "total_entries": len(entries),
        "by_gate": dict(by_gate),
        "by_gate_decision": {
            gate: dict(decisions)
            for gate, decisions in by_gate_decision.items()
        },
        "reasons_by_gate": dict(reasons_by_gate),
        "uniformly_allow_candidates": uniformly_allow,
    }


def _print_human(summary: dict[str, Any], since_text: str) -> None:
    """Print a human-readable summary."""
    print(f"Gate signal summary for the last {since_text}")
    print(f"  total entries: {summary['total_entries']}")
    if summary["total_entries"] == 0:
        return

    print()
    print("  by gate:")
    for gate, count in sorted(summary["by_gate"].items(), key=lambda x: -x[1]):
        decisions = summary["by_gate_decision"][gate]
        decision_str = ", ".join(
            f"{decision}={count}"
            for decision, count in sorted(decisions.items(), key=lambda x: -x[1])
        )
        print(f"    {gate}: {count}  ({decision_str})")

    if summary["uniformly_allow_candidates"]:
        print()
        print("  bloat candidates (≥5 firings, only 'allow' decisions):")
        for gate in summary["uniformly_allow_candidates"]:
            print(f"    {gate}")

    print()
    print("  reasons (per gate, deduplicated, up to 5 per gate):")
    for gate, reasons in summary["reasons_by_gate"].items():
        unique = []
        seen: set[str] = set()
        for r in reasons:
            if r not in seen:
                unique.append(r)
                seen.add(r)
            if len(unique) == 5:
                break
        for r in unique:
            print(f"    {gate}: {r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="7d",
                        help="window: '1d', '7d', '24h', '30m' (default 7d)")
    parser.add_argument("--gate", default=None,
                        help="filter to one gate by name")
    parser.add_argument("--decision", default=None,
                        help="filter to one decision (allow/deny/ask/...)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of human summary")
    args = parser.parse_args()

    try:
        since = _parse_since(args.since)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    signal_path = _resolve_signal_path()
    if signal_path is None:
        print("error: no .beads/ directory found from cwd or BEADS_DIR env var",
              file=sys.stderr)
        return 1
    if not signal_path.is_file():
        print(f"note: signal file does not exist yet at {signal_path}",
              file=sys.stderr)
        if args.json:
            print(json.dumps({"total_entries": 0}))
        else:
            print(f"Gate signal summary for the last {args.since}")
            print("  total entries: 0")
        return 0

    entries = _read_entries(signal_path, since, args.gate, args.decision)
    summary = _summarize(entries)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        _print_human(summary, args.since)

    return 0


if __name__ == "__main__":
    sys.exit(main())
