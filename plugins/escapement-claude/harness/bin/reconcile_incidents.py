#!/usr/bin/env python3
"""Close the `was_correct` loop on the continuation-harness incidents log.

`stop_hook.py` logs every Stop decision to `incidents.jsonl` with `was_correct`
set to `None` — correctness is not knowable at decision time. This reconciler
backfills `was_correct` (plus an auditable `label_basis`) retroactively, using the
**next genuine human reaction in the session transcript** as the independent oracle:

  - ALLOW followed by a bare "continue" / "keep going"  -> the work STALLED;
    the harness should have blocked. was_correct = False  (the false-allow rate
    is the effectiveness metric for "ongoing work shouldn't pause unnecessarily").
  - BLOCK followed by "stop" / an interrupt              -> the harness OVER-NAGGED;
    the agent was done. was_correct = False  (the false-block / friction rate).
  - ALLOW on a harness-PROVED terminal (verification_passed / user_released /
    conversational / queue_drained / wakeup_registered) with no contradicting user
    reaction                                             -> was_correct = True.
  - Anything ambiguous, or no transcript on disk         -> was_correct = None
    (FAIL CLOSED — a wrong label would poison the very metric we are building).

Design constraints (see .agent/runtime/test-oracle-brief.md):
  * stdlib only — `harness/bin/` must not import `claude/hooks/`.
  * default dry-run; `--write` persists via atomic temp-file replace.
  * idempotent — a definitive (True/False) label is never re-flipped; only `None`
    rows are re-attempted (so a transcript that appears later can still be labeled).

CLI:
  reconcile_incidents.py [--incidents PATH] [--projects-root PATH]
                         [--summary] [--write] [--relabel]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import re
from collections import Counter
from datetime import datetime

DEFAULT_INCIDENTS = pathlib.Path.home() / ".claude" / "harness" / "incidents.jsonl"
DEFAULT_PROJECTS = pathlib.Path.home() / ".claude" / "projects"

# An ALLOW on one of these reasons is one the harness itself defends: it either ran
# the contract oracle, the user released, there was nothing to finish, or nothing
# was actionable. A contradicting user reaction (see classify) still overrides.
TERMINAL_REASONS = frozenset({
    "verification_passed",
    "user_released",
    "conversational",
    "queue_drained",
    "wakeup_registered",
})

# A "verdict" message is a SHORT reaction to the prior stop. A longer message is a
# new instruction ("continue, but also refactor X") and must NOT be read as a verdict.
MAX_VERDICT_WORDS = 6

# Normalized (punctuation-stripped, lowercased) bare continuations: the user telling
# the agent to resume work it shouldn't have stopped.
_CONTINUATIONS = frozenset({
    "continue", "please continue", "continue please",
    "keep going", "keep going please", "go on", "carry on",
    "resume", "dont stop", "do not stop", "keep at it",
    "keep working", "continue working", "finish it",
    "you didnt finish", "you did not finish",
    "youre not done", "you are not done", "you arent done",
})

# Normalized bare releases: the user pushing back to stop after a block.
_RELEASES = frozenset({
    "stop", "please stop", "you can stop", "ok stop",
    "end here", "done for now", "thats enough", "that is enough",
    "enough", "were done", "we are done", "halt",
    "thats all", "that is all", "leave it", "stop for now", "lets stop",
})

_TAG_PREFIXES = ("<command-name>", "<command-message>", "<local-command",
                 "<system-reminder>", "<bash-")


# ---------------------------------------------------------------------------
# text normalization + lexical classifiers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    low = text.strip().lower()
    stripped = re.sub(r"[^\w\s]", " ", low)
    return re.sub(r"\s+", " ", stripped).strip()


def _is_short(norm: str) -> bool:
    return 0 < len(norm.split()) <= MAX_VERDICT_WORDS


def is_continuation(text: str) -> bool:
    norm = _normalize(text)
    return _is_short(norm) and norm in _CONTINUATIONS


def is_release(text: str) -> bool:
    if "interrupted by user" in text.strip().lower():
        return True
    norm = _normalize(text)
    return _is_short(norm) and norm in _RELEASES


# ---------------------------------------------------------------------------
# transcript parsing
# ---------------------------------------------------------------------------

def _parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_human_messages(lines):
    """Ordered (datetime|None, text) for GENUINE human prompts only.

    Excludes tool_result entries, `isMeta` injections, slash-command invocations,
    and `<system-reminder>`/caveat wrappers. Keeps the `[Request interrupted by
    user]` marker (itself a human reaction).
    """
    out = []
    for entry in lines:
        if not isinstance(entry, dict) or entry.get("type") != "user":
            continue
        if entry.get("isMeta"):
            continue
        msg = entry.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            # A list containing a tool_result is the tool-output turn, not a human.
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                continue
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            continue
        text = text.strip()
        if not text:
            continue
        low = text.lstrip().lower()
        if any(low.startswith(p) for p in _TAG_PREFIXES):
            continue
        out.append((_parse_ts(entry.get("timestamp")), text))
    return out


def next_human_after(human_msgs, decision_dt):
    """First genuine human message strictly after the decision timestamp."""
    if decision_dt is None:
        return None
    for dt, text in human_msgs:
        if dt is not None and dt > decision_dt:
            return text
    return None


# ---------------------------------------------------------------------------
# the core oracle (pure)
# ---------------------------------------------------------------------------

def classify(decision, reason, next_human_text):
    """Return (was_correct, label_basis). Pure; the heart of the reconciler.

    User reaction takes precedence over the reason-prior: a stop the harness thought
    valid but that the user immediately resumed is still a false allow (the contract
    oracle was too narrow).
    """
    has = bool(next_human_text and next_human_text.strip())
    cont = has and is_continuation(next_human_text)
    rel = has and is_release(next_human_text)

    if decision == "allow":
        if cont:
            return (False, "stalled_user_resumed")
        if rel:
            return (True, "user_confirmed_stop")
        # A substantive (non-verdict) human reaction outranks the reason-prior: we
        # cannot cleanly call the stop correct, and must not rubber-stamp it True.
        if has:
            return (None, "ambiguous_human")
        if reason in TERMINAL_REASONS:
            return (True, "harness_proved_terminal")
        return (None, "no_human_reaction")

    # block (and any non-allow decision): we measure over-nag (False) and absence
    # (None). We never claim a block was correct — that needs full-sequence proof
    # we deliberately do not assert here.
    if rel:
        return (False, "overnag_user_released")
    if cont:
        return (None, "ambiguous_block_continued")
    if has:
        return (None, "ambiguous_human")
    return (None, "no_human_reaction")


# ---------------------------------------------------------------------------
# reconcile + summarize
# ---------------------------------------------------------------------------

def reconcile(incidents, get_transcript, relabel=False):
    """Backfill was_correct/label_basis. `get_transcript(session_id) -> lines|None`.

    Returns (new_incidents, stats). Does not mutate the input. Idempotent: a row
    with a definitive True/False label is left untouched unless `relabel=True`;
    `None` rows are always re-attempted.
    """
    by_session = {}
    for rec in incidents:
        by_session.setdefault(rec.get("session_id"), []).append(rec)

    # Cache extracted human messages per session (one transcript read per session).
    human_cache = {}

    def humans_for(sid):
        if sid not in human_cache:
            lines = get_transcript(sid)
            human_cache[sid] = (extract_human_messages(lines) if lines else None)
        return human_cache[sid]

    out = []
    relabeled = 0
    for rec in incidents:
        new = dict(rec)
        already = new.get("was_correct")
        if already in (True, False) and not relabel:
            out.append(new)
            continue

        sid = new.get("session_id")
        humans = humans_for(sid)
        nxt = (next_human_after(humans, _parse_ts(new.get("timestamp")))
               if humans is not None else None)
        wc, basis = classify(new.get("decision"), new.get("reason"), nxt)
        # No transcript on disk and nothing else resolved it: record WHY (so the
        # row can be re-attempted later) rather than the generic no_human_reaction.
        # A harness-proved terminal still keeps its definitive label.
        if humans is None and wc is None:
            basis = "no_transcript"

        if (new.get("was_correct"), new.get("label_basis")) != (wc, basis):
            relabeled += 1
        new["was_correct"] = wc
        new["label_basis"] = basis
        out.append(new)

    stats = summarize(out)
    stats["relabeled"] = relabeled
    return out, stats


def _rate(numer, denom):
    return (numer / denom) if denom else None


def summarize(incidents):
    """Demonstrable-friction LOWER BOUNDS.

    A block is never labeled True (we don't assert "held correctly"), so a rate of
    false-blocks / labeled-blocks would be pinned at 100% by construction — a
    meaningless oracle. Instead both rates use ALL decisions of that type as the
    denominator and the demonstrable-False events as the numerator:

        stall rate   = (allows the user had to resume)  / (all allows)
        over-nag rate = (blocks the user pushed back on) / (all blocks)

    Both are honest lower bounds: "at least X% were demonstrably premature." The
    true rate among un-observed (no-transcript / no-reaction) decisions is unknown,
    which is why coverage is reported alongside.
    """
    total = len(incidents)
    total_allows = sum(1 for r in incidents if r.get("decision") == "allow")
    total_blocks = sum(1 for r in incidents if r.get("decision") == "block")
    labeled = sum(1 for r in incidents if r.get("was_correct") in (True, False))
    stalled = sum(1 for r in incidents if r.get("label_basis") == "stalled_user_resumed")
    overnag = sum(1 for r in incidents if r.get("label_basis") == "overnag_user_released")
    by_basis = Counter(r.get("label_basis") for r in incidents if r.get("label_basis"))
    return {
        "total": total,
        "labeled": labeled,
        "coverage": _rate(labeled, total),
        "total_allows": total_allows,
        "total_blocks": total_blocks,
        "stalled_allows": stalled,
        "overnag_blocks": overnag,
        "false_allow_rate": _rate(stalled, total_allows),
        "false_block_rate": _rate(overnag, total_blocks),
        "by_basis": dict(by_basis),
    }


# ---------------------------------------------------------------------------
# I/O + CLI
# ---------------------------------------------------------------------------

def load_incidents(path):
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def load_transcript(path):
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None
    return out


def make_transcript_finder(projects_root):
    root = str(projects_root)

    def finder(session_id):
        if not session_id:
            return None
        hits = glob.glob(os.path.join(root, "*", f"{session_id}.jsonl"))
        if not hits:
            return None
        return load_transcript(hits[0])

    return finder


def write_incidents_atomic(path, incidents):
    path = pathlib.Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        for rec in incidents:
            f.write(json.dumps(rec) + "\n")
    os.replace(tmp, path)


def _fmt_rate(r):
    return "n/a" if r is None else f"{r:.1%}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reconcile incidents.jsonl was_correct labels.")
    ap.add_argument("--incidents", default=str(DEFAULT_INCIDENTS))
    ap.add_argument("--projects-root", default=str(DEFAULT_PROJECTS))
    ap.add_argument("--write", action="store_true", help="persist labels (default: dry-run)")
    ap.add_argument("--relabel", action="store_true", help="re-attempt definitive labels too")
    ap.add_argument("--summary", action="store_true", help="print summary only")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing (for silent SessionStart auto-run; implies --write)")
    args = ap.parse_args(argv)

    incidents = load_incidents(args.incidents)
    finder = make_transcript_finder(args.projects_root)
    out, stats = reconcile(incidents, finder, relabel=args.relabel)

    # Quiet auto-run: persist labels, emit zero context. The half-life review / the
    # on-demand --summary surfaces the numbers; the SessionStart tick just maintains
    # them while transcripts are still on disk.
    if args.quiet:
        write_incidents_atomic(args.incidents, out)
        return 0

    print(f"incidents:        {stats['total']}")
    print(f"labeled:          {stats['labeled']}  (coverage {_fmt_rate(stats['coverage'])})")
    print(f"stall rate:       {_fmt_rate(stats['false_allow_rate'])} (lower bound)"
          f"  ({stats['stalled_allows']}/{stats['total_allows']} allows the user had "
          f"to resume = ongoing work paused unnecessarily)")
    print(f"over-nag rate:    {_fmt_rate(stats['false_block_rate'])} (lower bound)"
          f"  ({stats['overnag_blocks']}/{stats['total_blocks']} blocks the user "
          f"pushed back on = friction)")
    print("by basis:")
    for basis, n in sorted(stats["by_basis"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {basis}")

    if args.write:
        write_incidents_atomic(args.incidents, out)
        print(f"\nwrote {len(out)} rows -> {args.incidents}  (relabeled {stats['relabeled']})")
    else:
        print(f"\n(dry-run; would relabel {stats['relabeled']} rows — pass --write to persist)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
