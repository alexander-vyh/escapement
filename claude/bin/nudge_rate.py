#!/usr/bin/env python3
"""Measure how often the user had to poke a stalled agent.

The continuation harness exists to stop an agent ending its turn with work
still owed. Its gates, judges and wakers all report on themselves; none of them
reports the thing that actually matters, which is whether a human had to type
"continue" to get the work moving again.

That number is recoverable from the transcripts. A NUDGE is a typed user prompt
that carries no new information: "well?", "continue", "progress?", "keep going".
It is the user spending attention purely to restart a session, which is the
outcome the harness is supposed to make unnecessary.

Baseline established 2026-08-30..2026-09-06, before the continuation repairs in
PRs #222/#223/#224: 54 nudges across 475 typed prompts (11.4%), in 17 of 44
sessions, median 23 minutes of dead air before each one.

Usage:
  nudge_rate.py                 # last 7 days
  nudge_rate.py --since 14d
  nudge_rate.py --json
  nudge_rate.py --started-after 2026-09-07T07:05:00Z   # only post-fix sessions

A deployed gate is inert in an already-running session, so a session that began
before a harness change never gets that change. Long-lived sessions therefore
keep reporting the OLD behaviour for days and drag the rate up. --started-after
restricts the population to sessions that actually carry the change, which is
the only honest way to read this number right after a deploy.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import statistics

PROJECTS = os.path.expanduser("~/.claude/projects")

# A nudge carries no content: it only asks the agent to resume. Anything that
# names a file, a decision or a next step is real input and must not count, or
# the metric rewards a silent agent.
NUDGE = re.compile(
    r"^(?:"
    r"well[?.!]*|"
    r"(?:ok[.,]?\s*)?(?:please\s+)?(?:just\s+)?"
    r"(?:keep\s+(?:fucking\s+)?(?:going|working|at it)|continue|carry on|go on|"
    r"proceed|resume|go|keep it up)[?.!]*|"
    r"(?:so\s*)?progress[?.!]*|status[?.!]*|update[?.!]*|"
    r"still (?:waiting|going|there|working)[?.!]*|"
    r"why (?:the fuck )?(?:are|did) you (?:stopped?|stop|quit|give up).*|"
    r"why (?:have )?you stopped.*|you stopped.*|don'?t stop.*|"
    r"finish (?:it|the (?:job|work))[?.!]*|"
    r"and[?.!]*|next[?.!]*|more[?.!]*|(?:hello|hey|yo|\?+|\.+)"
    r")$",
    re.I,
)
MAX_NUDGE_CHARS = 45


def parse_since(token: str) -> dt.timedelta:
    unit = token[-1].lower()
    value = int(token[:-1])
    return {"d": dt.timedelta(days=value), "h": dt.timedelta(hours=value)}[unit]


def _text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def is_nudge(text: str) -> bool:
    collapsed = " ".join(text.split())
    return len(collapsed) <= MAX_NUDGE_CHARS and bool(NUDGE.match(collapsed))


def session_start(path: str) -> str | None:
    """Timestamp of the first record in a transcript, or None if unreadable."""
    try:
        with open(path, errors="replace") as handle:
            for line in handle:
                try:
                    stamp = json.loads(line).get("timestamp")
                except ValueError:
                    continue
                if stamp:
                    return stamp
    except OSError:
        return None
    return None


def collect(cutoff_iso: str, started_after: str | None = None) -> tuple[list[dict], list[dict]]:
    """Return (typed prompts, nudges) since cutoff, newest transcripts included."""
    typed: list[dict] = []
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        if "/subagents/" in path:
            continue
        if started_after:
            began = session_start(path)
            if began is None or began < started_after:
                continue
        try:
            handle = open(path, errors="replace")
        except OSError:
            continue
        with handle:
            prior_assistant_ts = None
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("isSidechain"):
                    continue
                stamp = record.get("timestamp") or ""
                if record.get("type") == "assistant":
                    prior_assistant_ts = stamp
                    continue
                if record.get("type") != "user":
                    continue
                # promptSource marks a real keystroke; sdk/system/queued are not.
                if record.get("promptSource") != "typed" or stamp < cutoff_iso:
                    continue
                text = _text(record.get("message") or {})
                if not text.strip():
                    continue
                typed.append(
                    {
                        "ts": stamp,
                        "cwd": record.get("cwd", ""),
                        "session": record.get("sessionId", ""),
                        "text": " ".join(text.split()),
                        "idle_s": _gap(prior_assistant_ts, stamp),
                    }
                )
    return typed, [row for row in typed if is_nudge(row["text"])]


def _gap(before: str | None, after: str) -> float | None:
    if not before:
        return None
    try:
        start = dt.datetime.fromisoformat(before.replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(after.replace("Z", "+00:00"))
    except ValueError:
        return None
    seconds = (end - start).total_seconds()
    return seconds if 0 < seconds < 86400 else None


def summarize(typed: list[dict], nudges: list[dict]) -> dict:
    idle = [row["idle_s"] for row in nudges if row["idle_s"] is not None]
    return {
        "typed_prompts": len(typed),
        "nudges": len(nudges),
        "nudge_rate": round(len(nudges) / len(typed), 4) if typed else 0.0,
        "sessions_total": len({row["session"] for row in typed}),
        "sessions_nudged": len({row["session"] for row in nudges}),
        "median_idle_s": round(statistics.median(idle)) if idle else None,
        "by_day": dict(collections.Counter(row["ts"][:10] for row in nudges)),
        "top_phrases": collections.Counter(
            row["text"].lower() for row in nudges
        ).most_common(8),
    }


def render(summary: dict, since_text: str) -> str:
    lines = [f"Nudge rate — last {since_text}"]
    if not summary["typed_prompts"]:
        lines.append("  no typed prompts in window")
        return "\n".join(lines)
    lines.append(
        f"  {summary['nudges']} nudges / {summary['typed_prompts']} typed prompts"
        f"  ({summary['nudge_rate']:.1%})"
    )
    lines.append(
        f"  sessions needing a poke: {summary['sessions_nudged']}"
        f" of {summary['sessions_total']}"
    )
    if summary["median_idle_s"] is not None:
        lines.append(
            f"  median dead air before a poke: {summary['median_idle_s'] / 60:.1f} min"
        )
    lines.append("")
    lines.append("  baseline 2026-08-30..09-06 (pre #222/#223/#224):"
                 " 54 / 475 = 11.4%, 17 of 44 sessions, 23 min median")
    if summary["top_phrases"]:
        lines.append("")
        lines.append("  most common:")
        for phrase, count in summary["top_phrases"]:
            lines.append(f"    {count:3d}  {phrase}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="7d", help="window, e.g. 7d or 48h")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--started-after",
        help="only sessions begun at/after this ISO stamp — use a deploy time so "
        "long-running pre-change sessions do not confound the reading",
    )
    args = parser.parse_args()

    cutoff = dt.datetime.now(dt.timezone.utc) - parse_since(args.since)
    typed, nudges = collect(
        cutoff.isoformat().replace("+00:00", "Z"), args.started_after
    )
    summary = summarize(typed, nudges)
    print(json.dumps(summary, indent=2) if args.json else render(summary, args.since))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
