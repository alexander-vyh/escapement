#!/usr/bin/env python3
"""Aggregate gate-signal logs across all repos under ~/GitHub.

Per claude/rules/gate-design.md Rule 2: every gate produces persistent
signal. This script reads `.beads/.gate-signal.jsonl` from every repo it
finds and reports aggregated patterns:

  - which gates fired most, in which repos
  - which gates have NEVER fired (candidates for petrification review)
  - which gates show mock-bureaucracy risk (high waiver:deny ratio,
    Wiesche et al. 2013) — symbolic compliance without behavior change
  - per-category counts for `validate_no_shirking` (the 8 anti-pattern
    classes — half-life query per Operating Rule 1)

Intended to run weekly via a Claude Code scheduled agent or launchd
job. Output is human-readable by default; pass --json for machine output.

## Usage

    python3 ~/.claude/bin/gate_signal_monitor.py [--since 7d]
                                                 [--root ~/GitHub]
                                                 [--json]
                                                 [--known-gates <gate>,...]

The --known-gates argument is used to detect "silent" gates — gates
that exist as hooks but never appear in the signal log. Defaults to
the 14 gates migrated as of 2026-05-27.
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


_DEFAULT_KNOWN_GATES = [
    "spec_id_enforcement",
    "discovery_gate",
    "discovery_input_gate",
    "tdd_gate",
    "no_direct_send_guard",
    "serena_preference_gate",
    "outcome_assertion_gate",
    "context_burn_detector",
    "review_gate",
    "discovery_close_gate",
    "enforce_named_agents",
    "test_oracle_brief_gate",
    "oracle_downgrade_warning_gate",
    "implementation_echo_test_gate",
    "validate_no_shirking",
]


def _parse_since(token: str) -> timedelta:
    suffix_map = {"d": "days", "h": "hours", "m": "minutes"}
    suffix = token[-1].lower()
    if suffix not in suffix_map:
        raise ValueError(f"unrecognized suffix in --since '{token}'")
    return timedelta(**{suffix_map[suffix]: int(token[:-1])})


def find_signal_logs(root: Path) -> list[Path]:
    """Return all `.beads/.gate-signal.jsonl` files under root."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    for entry in root.iterdir():
        if not entry.is_dir() or entry.is_symlink():
            continue
        signal_log = entry / ".beads" / ".gate-signal.jsonl"
        if signal_log.is_file():
            out.append(signal_log)
    return sorted(out)


def read_entries(
    signal_path: Path, cutoff: datetime,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with signal_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = entry.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                entries.append(entry)
    except OSError:
        pass
    return entries


def analyze(
    entries_by_repo: dict[str, list[dict[str, Any]]],
    known_gates: list[str],
) -> dict[str, Any]:
    """Roll up per-gate, per-decision, per-category counts."""
    by_gate: Counter[str] = Counter()
    by_repo: Counter[str] = Counter()
    by_gate_decision: dict[str, Counter[str]] = defaultdict(Counter)
    by_gate_repo: dict[str, Counter[str]] = defaultdict(Counter)
    shirking_categories: Counter[str] = Counter()
    shirking_waivers_by_category: Counter[str] = Counter()
    reasons_by_gate: dict[str, list[str]] = defaultdict(list)

    total = 0
    for repo, entries in entries_by_repo.items():
        for e in entries:
            total += 1
            gate = e.get("gate", "?")
            decision = e.get("decision", "?")
            by_gate[gate] += 1
            by_repo[repo] += 1
            by_gate_decision[gate][decision] += 1
            by_gate_repo[gate][repo] += 1
            reason = e.get("reason", "")
            if reason and len(reasons_by_gate[gate]) < 30:
                reasons_by_gate[gate].append(reason)

            # validate_no_shirking has categories — track separately
            if gate == "validate_no_shirking":
                cat = (e.get("extras") or {}).get("category", "uncategorized")
                if decision == "deny":
                    shirking_categories[cat] += 1
                elif decision == "waiver-accepted":
                    shirking_waivers_by_category[cat] += 1

    # Mock-bureaucracy risk: gates where waivers/asks outnumber denies+allows
    # (i.e. the user is overriding more than enforcing) — gate-design.md Rule 3.
    mock_risk: list[dict[str, Any]] = []
    for gate, decisions in by_gate_decision.items():
        deny_count = decisions.get("deny", 0)
        waiver_count = (
            decisions.get("waiver-accepted", 0) + decisions.get("override-applied", 0)
        )
        if deny_count > 0 and waiver_count > deny_count:
            mock_risk.append({
                "gate": gate,
                "denies": deny_count,
                "waivers": waiver_count,
                "ratio": round(waiver_count / max(deny_count, 1), 2),
            })

    # Silent gates: in known list but absent from signal — petrification
    # candidates per Operating Rule 1.
    fired = set(by_gate.keys())
    silent = sorted(g for g in known_gates if g not in fired)

    # Shirking categories with high waiver:deny ratio → false-positive heavy
    shirking_fp_heavy: list[dict[str, Any]] = []
    for cat in set(shirking_categories) | set(shirking_waivers_by_category):
        denies = shirking_categories[cat]
        waivers = shirking_waivers_by_category[cat]
        if denies + waivers >= 3 and waivers > denies:
            shirking_fp_heavy.append({
                "category": cat,
                "denies": denies,
                "waivers": waivers,
                "ratio": round(waivers / max(denies, 1), 2),
            })

    return {
        "total_events": total,
        "by_gate": dict(by_gate),
        "by_repo": dict(by_repo),
        "by_gate_decision": {g: dict(d) for g, d in by_gate_decision.items()},
        "by_gate_repo": {g: dict(r) for g, r in by_gate_repo.items()},
        "silent_known_gates": silent,
        "mock_bureaucracy_risk": sorted(mock_risk, key=lambda x: -x["ratio"]),
        "shirking_categories": dict(shirking_categories),
        "shirking_fp_heavy": sorted(shirking_fp_heavy, key=lambda x: -x["ratio"]),
        "reasons_by_gate_sample": {
            g: list(dict.fromkeys(rs))[:5]  # dedup, keep first 5
            for g, rs in reasons_by_gate.items()
        },
    }


def render_human(summary: dict[str, Any], since_text: str) -> str:
    lines: list[str] = []
    lines.append(f"Gate-signal monitor — last {since_text}")
    lines.append(f"  total events: {summary['total_events']}")
    lines.append(f"  repos active: {len(summary['by_repo'])}")

    if summary["total_events"] == 0:
        lines.append("")
        lines.append("  No gate activity. Either no real work happened, or hooks aren't")
        lines.append("  deployed correctly. Run: ls -la ~/.claude/hooks/_gate_signal.py")
        return "\n".join(lines)

    lines.append("")
    lines.append("By gate (top 10):")
    by_gate = summary["by_gate"]
    for gate, count in sorted(by_gate.items(), key=lambda x: -x[1])[:10]:
        decisions = summary["by_gate_decision"][gate]
        dstr = ", ".join(
            f"{d}={n}" for d, n in sorted(decisions.items(), key=lambda x: -x[1])
        )
        lines.append(f"  {gate}: {count}  ({dstr})")

    lines.append("")
    lines.append("By repo:")
    for repo, count in sorted(summary["by_repo"].items(), key=lambda x: -x[1]):
        lines.append(f"  {repo}: {count}")

    if summary["mock_bureaucracy_risk"]:
        lines.append("")
        lines.append("⚠️  MOCK-BUREAUCRACY RISK (waivers > denies — gate may be too aggressive):")
        for m in summary["mock_bureaucracy_risk"]:
            lines.append(f"  {m['gate']}: {m['waivers']} waivers vs {m['denies']} denies (ratio {m['ratio']})")

    if summary["silent_known_gates"]:
        lines.append("")
        lines.append("Silent gates (known but never fired in window — candidates for half-life review):")
        for g in summary["silent_known_gates"]:
            lines.append(f"  {g}")

    if summary["shirking_fp_heavy"]:
        lines.append("")
        lines.append("⚠️  validate_no_shirking — categories with high waiver ratio (false-positive-heavy):")
        for c in summary["shirking_fp_heavy"]:
            lines.append(f"  {c['category']}: {c['waivers']} waivers vs {c['denies']} denies (ratio {c['ratio']})")
    elif summary["shirking_categories"]:
        lines.append("")
        lines.append("validate_no_shirking — counts by anti-pattern category:")
        for cat, n in sorted(summary["shirking_categories"].items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {n}")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    p.add_argument("--since", default="7d", help="window: '1d', '7d', '30d' (default 7d)")
    p.add_argument(
        "--root",
        type=Path,
        default=Path(os.path.expanduser("~/GitHub")),
        help="directory to scan for repos (default: ~/GitHub)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    p.add_argument(
        "--known-gates",
        default=",".join(_DEFAULT_KNOWN_GATES),
        help="comma-separated gate names used to detect 'silent' gates",
    )
    args = p.parse_args()

    try:
        since = _parse_since(args.since)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    cutoff = datetime.now(timezone.utc) - since
    known_gates = [g.strip() for g in args.known_gates.split(",") if g.strip()]

    logs = find_signal_logs(args.root)
    entries_by_repo: dict[str, list[dict[str, Any]]] = {}
    for log_path in logs:
        # Repo name = parent of the .beads/ directory
        repo_name = log_path.parent.parent.name
        entries = read_entries(log_path, cutoff)
        if entries:
            entries_by_repo[repo_name] = entries

    summary = analyze(entries_by_repo, known_gates)
    summary["window"] = args.since
    summary["root"] = str(args.root)
    summary["logs_scanned"] = len(logs)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(render_human(summary, args.since))

    return 0


if __name__ == "__main__":
    sys.exit(main())
